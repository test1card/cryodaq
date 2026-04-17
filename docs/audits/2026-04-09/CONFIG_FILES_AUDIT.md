# CryoDAQ Configuration Files Audit

**Date:** 2026-04-09
**Branch:** `master`
**Scope:** `config/*.yaml`, `config/*.yaml.example`, `config/experiment_templates/*.yaml`, and every loader/consumer that reads them
**Config files audited:** 18

## Summary

- `HIGH`: 4
- `MEDIUM`: 4
- `LOW`: 1
- `OK`: 4

Main result: the codebase has no unified config schema layer. Some configs fail closed, some fail open, and `.local.yaml` overrides are full-file replacement rather than merge. In a safety-critical system, that means a partial local override can silently remove guards instead of narrowly overriding one parameter.

## Loader Matrix

| Config file | Runtime loader(s) | Missing file | Malformed / wrong top-level type | Unknown fields | Verdict |
|---|---|---|---|---|---|
| `config/instruments.yaml` | `engine._cfg()` + `_load_drivers()` | engine startup aborts on missing selected file | startup aborts on bad structure / bad types | ignored | no schema, fail-fast |
| `config/instruments.local.yaml.example` | template only | not loaded | n/a | n/a | docs/example only |
| `config/channels.yaml` | `ChannelManager.load()` | silent fallback to baked-in defaults | logs error, falls back to baked-in defaults | ignored | GUI fail-open |
| `config/safety.yaml` | `SafetyManager.load_config()` | warning and keep defaults | some values raise, some silently coerce, invalid regex only logged | ignored | safety fail-open |
| `config/interlocks.yaml` | `InterlockEngine.load_config()` | engine logs warning and continues without interlocks | raises and aborts startup path | ignored | fail-fast if file exists |
| `config/alarms.yaml` | `AlarmEngine.load_config()` | engine logs warning and continues without legacy alarms | raises and aborts startup path | ignored | fail-fast if file exists |
| `config/alarms_v3.yaml` | `load_alarm_config()` + housekeeping protection loader | silently disables v2 alarms | non-dict returns empty config silently | mostly ignored | silent disable |
| `config/housekeeping.yaml` | `load_housekeeping_config()` | empty dict, throttle/retention use defaults | parse exception bubbles | ignored | no schema |
| `config/plugins.yaml` | `engine.py` built-in analytics config only | built-ins disabled | parse exception bubbles | ignored | split config model |
| `config/cooldown.yaml` | `engine.py` | cooldown service disabled | caught and logged, service not created | ignored | soft-disable |
| `config/notifications.yaml` | `engine.py`, `TelegramNotifier.from_config()` | notifications disabled or constructor raises depending on caller | engine logs and disables notifications | ignored | soft-disable |
| `config/notifications.local.yaml.example` | template only | not loaded | n/a | n/a | docs/example only |
| `config/shifts.yaml` | `load_shift_config()` | feature disabled | warning + empty dict | ignored | GUI fail-open |
| `config/experiment_templates/*.yaml` | `ExperimentManager._load_templates()` | template absent = just unavailable | invalid template raises and aborts | ignored | strict enough |

## Findings

### C.1 [HIGH] Partial `.local.yaml` overrides replace the whole base file, not merge with it

**Why this matters:** engine path selection is generic for all configs. If an operator creates `safety.local.yaml` or `notifications.local.yaml` with only one field override, the base file is not merged in. Missing keys fall back to defaults, which for safety can remove critical channel checks.

**YAML / config surface:**

The repository already documents `.local.yaml` as the preferred operator override mechanism:

```yaml
# config/instruments.local.yaml.example
# Этот файл НЕ коммитится в git (*.local.yaml в .gitignore).
# Если instruments.local.yaml существует — engine использует его вместо instruments.yaml.
```

```yaml
# config/notifications.local.yaml.example
# Этот файл НЕ коммитится в git (*.local.yaml в .gitignore).
telegram:
  bot_token: "ВСТАВЬТЕ_ТОКЕН_ОТ_BOTFATHER"
```

**Loader code:**

```python
# src/cryodaq/engine.py:775-783
def _cfg(name: str) -> Path:
    local = _CONFIG_DIR / f"{name}.local.yaml"
    return local if local.exists() else _CONFIG_DIR / f"{name}.yaml"

instruments_cfg = _cfg("instruments")
alarms_cfg = _cfg("alarms")
interlocks_cfg = _cfg("interlocks")
housekeeping_cfg = _cfg("housekeeping")
```

```python
# src/cryodaq/core/safety_manager.py:124-155
def load_config(self, path: Path) -> None:
    if not path.exists():
        logger.warning("safety.yaml not found: %s", path)
        return

    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    patterns: list[re.Pattern[str]] = []
    for pattern in raw.get("critical_channels", []):
        ...
    self._config = SafetyConfig(
        critical_channels=patterns,
        stale_timeout_s=float(raw.get("stale_timeout_s", 10.0)),
        ...
    )
```

**Actual impact:** this is not a merge override model. A local file containing only `stale_timeout_s: 20` will implicitly erase `critical_channels`, source limits, and any other missing sections by replacing them with defaults. On `safety.yaml`, that means a well-intentioned local tweak can silently turn off the critical-channel freshness gate and make `request_run()` rely on an empty critical set. The same pattern also applies to alarms, interlocks, housekeeping, plugins, cooldown, and notifications, but `safety.yaml` is the dangerous case because the defaults are not safety-equivalent to the committed base file.

**Recommendation:** either stop using generic full-file `.local.yaml` selection for safety-critical configs, or implement deep merge with schema validation and an explicit log of the merged effective config. At minimum, refuse partial local overrides for `safety`, `interlocks`, and `alarms_v3`.

---

### C.2 [HIGH] `safety.yaml` can fail open to zero critical channels while startup continues

**Why this matters:** `critical_channels` are the basis for stale-data gating before a run is allowed. Missing file or invalid regex entries do not stop startup.

**YAML / config surface:**

```yaml
# config/safety.yaml
critical_channels:
  - "Т1 .*"
  - "Т7 .*"
  - "Т11 .*"
  - "Т12 .*"
stale_timeout_s: 10.0
heartbeat_timeout_s: 15.0
```

**Loader and use site:**

```python
# src/cryodaq/core/safety_manager.py:124-155
def load_config(self, path: Path) -> None:
    if not path.exists():
        logger.warning("safety.yaml not found: %s", path)
        return

    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    patterns: list[re.Pattern[str]] = []
    for pattern in raw.get("critical_channels", []):
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            logger.error("Invalid critical_channels regex %r: %s", pattern, exc)

    self._config = SafetyConfig(
        critical_channels=patterns,
        stale_timeout_s=float(raw.get("stale_timeout_s", 10.0)),
        ...
    )
```

```python
# src/cryodaq/core/safety_manager.py:601-619
def _check_preconditions(self) -> tuple[bool, str]:
    now = time.monotonic()

    for pattern in self._config.critical_channels:
        matched = False
        for ch, (ts, value, status) in self._latest.items():
            if not pattern.match(ch):
                continue
            matched = True
            age = now - ts
            if age > self._config.stale_timeout_s:
                return False, f"Stale data: {ch} ({age:.1f}s)"
            ...
        if not matched and not self._mock:
            return False, f"No data for critical channel: {pattern.pattern}"
```

**Actual impact:** if `safety.yaml` is absent, `load_config()` just returns and leaves `critical_channels` at the dataclass default `[]`. If the file exists but every regex is malformed, the loader only logs errors and still commits the resulting empty list. In both cases, `_check_preconditions()` skips the critical-channel loop entirely, so run permission no longer requires any fresh temperature telemetry from `Т1`, `Т7`, `Т11`, or `Т12`.

**Recommendation:** treat missing `safety.yaml`, empty `critical_channels`, or regex compile failures as startup-fatal. For safety-critical configs, “log and continue” is the wrong failure mode.

---

### C.3 [HIGH] `alarms_v3.yaml` has a live-looking `interlocks:` section that no runtime path actually enforces

**Why this matters:** the file contains safety-looking actions like `emergency_off` and `stop_source`, but runtime interlock enforcement still comes from `config/interlocks.yaml`.

**YAML / config surface:**

```yaml
# config/alarms_v3.yaml
interlocks:
  overheat_cryostat:
    channel_group: all_temp
    check: any_above
    threshold: 350
    action: emergency_off

  keithley_overpower_interlock:
    channels: [smua_power, smub_power]
    check: any_above
    threshold: 4.5
    action: stop_source
```

**Loader code:**

```python
# src/cryodaq/core/alarm_config.py:71-111
def load_alarm_config(
    path: str | Path | None = None,
) -> tuple[EngineConfig, list[AlarmConfig]]:
    ...
    # --- Global alarms ---
    for alarm_id, alarm_raw in raw.get("global_alarms", {}).items():
        cfg = _expand_alarm(alarm_id, alarm_raw, channel_groups)
        if cfg is not None:
            alarms.append(cfg)

    # --- Phase alarms ---
    for phase_name, phase_dict in raw.get("phase_alarms", {}).items():
        ...
            alarms.append(cfg)

    return engine_cfg, alarms
```

```python
# src/cryodaq/engine.py:862-925
alarm_engine = AlarmEngine(broker)
if alarms_cfg.exists():
    alarm_engine.load_config(alarms_cfg)
...
interlock_engine = InterlockEngine(
    broker,
    actions=interlock_actions,
    trip_handler=_interlock_trip_handler,
)
if interlocks_cfg.exists():
    interlock_engine.load_config(interlocks_cfg)
```

```python
# src/cryodaq/core/housekeeping.py:178-184
interlocks = data.get("interlocks") or {}
if isinstance(interlocks, dict):
    for _name, interlock in interlocks.items():
        if isinstance(interlock, dict):
            refs.extend(_extract_channel_refs(interlock))
```

**Actual impact:** editing `alarms_v3.yaml` can change housekeeping protection patterns, but it does not change the actual `InterlockEngine` trip logic. That is a dangerous split-brain config surface: an engineer can update thresholds in one file, see valid YAML, restart the system, and still have the old enforcement from `interlocks.yaml`. In a safety review, a config section named `interlocks` with `action: emergency_off` is expected to be authoritative; here it is not.

**Recommendation:** remove the dead `interlocks:` section from `alarms_v3.yaml`, or wire it into a real runtime loader and deprecate `interlocks.yaml` with one authoritative source. Two safety config files with different semantics is unacceptable.

---

### C.4 [HIGH] A malformed `alarms_v3.yaml` silently disables the v2 alarm engine instead of failing startup

**Why this matters:** `alarms_v3.yaml` carries stale/data-loss alarms, setpoint deviations, and phase alarms. Wrong top-level structure becomes “empty config” rather than a startup error.

**YAML / config surface:**

```yaml
# config/alarms_v3.yaml
engine:
  poll_interval_s: 0.5
  rate_window_s: 120
  rate_min_points: 60

global_alarms:
  data_stale_temperature:
    alarm_type: stale
    channel_group: all_temp
    timeout_s: 30
```

**Loader and engine wiring:**

```python
# src/cryodaq/core/alarm_config.py:81-90
if path is None:
    path = _find_default_config()
if path is None or not Path(path).exists():
    return EngineConfig(), []

with open(path, encoding="utf-8") as f:
    raw = yaml.safe_load(f)

if not isinstance(raw, dict):
    return EngineConfig(), []
```

```python
# src/cryodaq/engine.py:938-959
_alarms_v3_cfg = _CONFIG_DIR / "alarms_v3.yaml"
_alarm_v2_engine_cfg, _alarm_v2_configs = load_alarm_config(_alarms_v3_cfg)
...
if _alarm_v2_configs:
    logger.info("Alarm Engine v2: загружено %d алармов", len(_alarm_v2_configs))
else:
    logger.info("Alarm Engine v2: config/alarms_v3.yaml не найден, v2 отключён")
```

**Actual impact:** a top-level YAML mistake that changes the parsed value from `dict` to scalar/list does not look like a config error to the engine. The alarm engine is simply disabled and the log message is misleading: it says the file was “not found” even though the real problem is “found but malformed”. That is a bad operational mode for stale/data-loss alarms because it degrades a config error into an observability feature silently disappearing.

**Recommendation:** differentiate “missing file” from “malformed file”, and fail startup if `alarms_v3.yaml` exists but cannot be parsed into a valid config dict. Safety-relevant alarms should not soft-disable on schema errors.

---

### C.5 [MEDIUM] `housekeeping.yaml` still uses Latin `T` in `include_patterns` while canonical runtime channels are Cyrillic `Т`

**YAML / config surface:**

```yaml
# config/housekeeping.yaml
adaptive_throttle:
  include_patterns:
    - "^T(?![1-8] ).*"
    - "pressure"
```

```yaml
# config/channels.yaml
channels:
  Т1:
    name: Криостат верх
  Т2:
    name: Криостат низ
  ...
```

```yaml
# config/instruments.yaml
channels:
  1: "Т1 Криостат верх"
  2: "Т2 Криостат низ"
```

**Loader and matcher code:**

```python
# src/cryodaq/core/housekeeping.py:216-225
class AdaptiveThrottle:
    def __init__(self, config: dict[str, Any] | None = None, *, protected_patterns: list[str] | None = None) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self._include = [re.compile(str(item)) for item in cfg.get("include_patterns", [])]
        self._exclude = [re.compile(str(item)) for item in cfg.get("exclude_patterns", [])]
```

```python
# src/cryodaq/core/housekeeping.py:262-275
def _should_emit(self, reading: Reading) -> bool:
    ...
    if self._matches_any(reading.channel, self._exclude):
        return True
    if self._include and not self._matches_any(reading.channel, self._include):
        return True
```

**What I checked:** `grep -rn "Т[0-9]" src/cryodaq/` returned 50 hits; `grep -rn "T[0-9]" src/cryodaq/` returned 13 hits, but the only live config regex for channel matching was the Latin `^T...` line above. Canonical runtime config uses Cyrillic `Т`.

**Impact:** the throttle include regex does not match the real temperature channels, so those readings take the `return True` path and bypass throttling entirely. This is not a direct safety disable, but it invalidates disk-growth assumptions and makes the throttle config look stricter than it actually is.

**Recommendation:** switch the pattern to canonical Cyrillic `^Т...`, or explicitly support both glyphs. Then log the effective compiled include patterns at startup.

---

### C.6 [MEDIUM] `data_stale_temperature.timeout_s` has zero margin over adaptive throttle `max_interval_s`

**YAML / config surface:**

```yaml
# config/alarms_v3.yaml
data_stale_temperature:
  alarm_type: stale
  channel_group: all_temp
  timeout_s: 30
```

```yaml
# config/housekeeping.yaml
adaptive_throttle:
  max_interval_s: 30.0
  stable_duration_s: 120.0
```

**Loader / use code:**

```python
# src/cryodaq/core/alarm_config.py:118-133
def _parse_engine_config(raw: dict) -> EngineConfig:
    ...
    return EngineConfig(
        poll_interval_s=float(raw.get("poll_interval_s", 2.0)),
        rate_window_s=float(raw.get("rate_window_s", 120.0)),
        rate_min_points=int(raw.get("rate_min_points", 60)),
```

```python
# src/cryodaq/core/housekeeping.py:297-306
stable_for = (now - state.stable_since).total_seconds()
since_emit = (now - state.last_emitted_at).total_seconds()
if stable_for < self._stable_duration_s:
    ...
if since_emit >= self._max_interval_s:
    state.last_emitted_value = reading.value
    state.last_emitted_at = now
    return True
```

**Impact:** the archive throttle is allowed to wait up to 30 seconds before re-emitting a stable reading, and the stale alarm also fires at 30 seconds. That leaves no jitter budget for scheduler drift, event-loop delays, or timestamp skew. This re-confirms the earlier hardening concern, but here the problem is visible directly in committed YAML values.

**Recommendation:** keep the stale alarm threshold comfortably above the maximum throttle interval, or mark stale alarms to consume the unthrottled stream only. Equal thresholds are brittle.

---

### C.7 [MEDIUM] `plugins.yaml` is not the authoritative plugin inventory

**YAML / config surface:**

```yaml
# config/plugins.yaml
sensor_diagnostics:
  enabled: true
  update_interval_s: 10
  ...

vacuum_trend:
  enabled: true
  ...
```

**Runtime loading code:**

```python
# src/cryodaq/engine.py:962-989
_plugins_cfg_path = _cfg("plugins")
_plugins_raw: dict[str, Any] = {}
if _plugins_cfg_path.exists():
    with _plugins_cfg_path.open(encoding="utf-8") as fh:
        _plugins_raw = yaml.safe_load(fh) or {}
_sd_cfg = _plugins_raw.get("sensor_diagnostics", {})
...
_vt_cfg = _plugins_raw.get("vacuum_trend", {})
```

```python
# src/cryodaq/analytics/plugin_loader.py:186-193
config_path = path.with_suffix(".yaml")
if config_path.exists():
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            config: dict[str, Any] = yaml.safe_load(fh) or {}
        plugin.configure(config)
```

**Cross-reference result:** root `plugins/` contains `cooldown_estimator.py`, `phase_detector.py`, and `thermal_calculator.py`, each with its own sidecar YAML. None of those plugin IDs appear in `config/plugins.yaml`. Conversely, the `plugins.yaml` keys `sensor_diagnostics` and `vacuum_trend` are built-in analytics modules, not root plugin files.

**Impact:** an operator reading `config/plugins.yaml` does not get the full analytics/plugin picture. Disabling built-ins there does nothing to root `plugins/*.py`, because the `PluginPipeline` loads those from the filesystem independently. That split model is operationally confusing and makes change review harder.

**Recommendation:** either move all plugin inventory into one authoritative config file, or rename `plugins.yaml` to something narrower like `analytics_builtin.yaml`. The current naming implies authority it does not have.

---

### C.8 [MEDIUM] `shifts.yaml` contains dead `shift_channels` keys that no loader consumes

**YAML / config surface:**

```yaml
# config/shifts.yaml
periodic_interval_hours: 2
periodic_missed_timeout_minutes: 15

operators:
  - "Фоменко В.Н."

shift_channels:
  temperature: "Т2"
  pressure: "Давление"
```

**Loader and usage code:**

```python
# src/cryodaq/gui/widgets/shift_handover.py:49-58
def load_shift_config() -> dict[str, Any]:
    try:
        if _CONFIG_PATH.exists():
            with _CONFIG_PATH.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("Failed to load %s", _CONFIG_PATH, exc_info=True)
    return {}
```

```python
# src/cryodaq/gui/widgets/shift_handover.py:470-474
interval_h = float(self._config.get("periodic_interval_hours", 2))
self._periodic_interval_ms = int(interval_h * 3600 * 1000)
self._missed_timeout_ms = int(
    float(self._config.get("periodic_missed_timeout_minutes", 15)) * 60 * 1000
)
```

**Impact:** the runtime only consumes `operators`, `periodic_interval_hours`, and `periodic_missed_timeout_minutes`. `shift_channels.temperature` and `shift_channels.pressure` are dead config today, and `pressure: "Давление"` would not match the real runtime pressure channel namespace anyway. This is not a direct safety bug, but it is a misleading config surface.

**Recommendation:** remove dead keys from `shifts.yaml`, or implement the feature and validate channel names against runtime inventory. Dead config is how operators lose trust in the rest of the file.

---

### C.9 [LOW] `channels.yaml` parsing errors silently fall back to baked-in defaults

**YAML / config surface:**

```yaml
# config/channels.yaml
channels:
  Т1:
    name: Криостат верх
    visible: true
    group: криостат
```

**Loader code:**

```python
# src/cryodaq/core/channel_manager.py:78-89
if self._config_path.exists():
    try:
        with self._config_path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        self._channels = raw.get("channels", {})
        logger.info("Загружена конфигурация каналов: %s", self._config_path)
    except Exception as exc:
        logger.error("Ошибка загрузки channels.yaml: %s", exc)
        self._channels = dict(_DEFAULT_CHANNELS)
else:
    self._channels = dict(_DEFAULT_CHANNELS)
```

**Impact:** this only affects display names/visibility/grouping, not core acquisition, so severity is low. But a malformed `channels.yaml` will be masked by internal defaults, which makes config mistakes harder for an operator to notice.

**Recommendation:** keep the fallback, but surface it in the GUI as “config invalid, defaults active” rather than only logging.

---

### C.10 [OK] `interlocks.yaml` patterns do match the real configured temperature channels

**YAML evidence:**

```yaml
# config/interlocks.yaml
- name: "overheat_cryostat"
  channel_pattern: "Т[1-8] .*"

- name: "overheat_compressor"
  channel_pattern: "Т(9|10|11|12) .*"

- name: "detector_warmup"
  channel_pattern: "Т12 .*"
```

```yaml
# config/instruments.yaml
1: "Т1 Криостат верх"
...
4: "Т12 Теплообменник 2"
```

**Loader code:**

```python
# src/cryodaq/core/interlock.py:225-238
with config_path.open(encoding="utf-8") as fh:
    raw: dict[str, Any] = yaml.safe_load(fh)

entries = raw.get("interlocks", [])
...
condition = InterlockCondition(
    name=entry["name"],
    description=entry["description"],
    channel_pattern=entry["channel_pattern"],
```

**Verdict:** the committed patterns are syntactically valid and do correspond to actual full channel names from `config/instruments.yaml`. I did not find a silent “matches nothing” bug in the current committed interlock file.

---

### C.11 [OK] Example secret files are separated from runtime local files, and `notifications.local.yaml` is actually gitignored

**YAML evidence:**

```yaml
# config/notifications.yaml
telegram:
  bot_token: "YOUR_BOT_TOKEN_HERE"
  chat_id: 0
```

```yaml
# config/notifications.local.yaml.example
telegram:
  bot_token: "ВСТАВЬТЕ_ТОКЕН_ОТ_BOTFATHER"
  chat_id: 0
```

**Loader / ignore evidence:**

```python
# src/cryodaq/engine.py:1328-1337
notifications_cfg = _cfg("notifications")
if notifications_cfg.exists():
    ...
    bot_token = str(tg_cfg.get("bot_token", ""))
    token_valid = bot_token and bot_token != "YOUR_BOT_TOKEN_HERE"
```

```text
$ git check-ignore -v config/notifications.local.yaml
.gitignore:33:config/*.local.yaml	config/notifications.local.yaml
```

**Verdict:** the separation model is real. The problem is not “secret file accidentally committed”; the problem is that runtime handling of placeholder/missing values is soft-disable rather than hard validation.

---

### C.12 [OK] Experiment templates are validated more strictly than most other config files

**YAML evidence:**

```yaml
# config/experiment_templates/calibration.yaml
id: calibration
name: Калибровка датчиков
sections:
  - setup
  - reference
  - operator_log
```

**Loader code:**

```python
# src/cryodaq/core/experiment.py:917-945
for path in sorted(templates_dir.glob("*.yaml")):
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    template_id = str(raw.get("id", "")).strip()
    if not template_id:
        raise ValueError(f"Experiment template {path} is missing 'id'.")
    name = str(raw.get("name", "")).strip()
    sections = tuple(str(item) for item in raw.get("sections", []) if str(item).strip())
    if not name or not sections:
        raise ValueError(f"Experiment template {path} is missing required fields.")
```

**Verdict:** unlike most configs, template loading rejects missing `id`, missing `name`, and empty `sections` rather than silently defaulting. That is the right pattern for experiment-definition files.

---

### C.13 [OK] Legacy `alarms.yaml` and `interlocks.yaml` loaders fail fast on malformed structure

**YAML evidence:**

```yaml
# config/alarms.yaml
alarms:
  - name: keithley_overpower
    channel_pattern: ".*/power"
```

```yaml
# config/interlocks.yaml
interlocks:
  - name: "overheat_cryostat"
    action: "emergency_off"
```

**Loader code:**

```python
# src/cryodaq/core/alarm.py:249-275
entries = raw.get("alarms", [])
if not isinstance(entries, list):
    raise ValueError(...)
...
severity = AlarmSeverity[severity_raw.upper()]
...
threshold=float(entry["threshold"])
```

```python
# src/cryodaq/core/interlock.py:228-238
entries = raw.get("interlocks", [])
if not isinstance(entries, list):
    raise ValueError(...)
...
condition = InterlockCondition(
    name=entry["name"],
    description=entry["description"],
    channel_pattern=entry["channel_pattern"],
```

**Verdict:** these older loaders are crude, but they do at least stop on malformed structure instead of silently disabling the subsystem. The inconsistency is with `safety.yaml`, `alarms_v3.yaml`, and GUI configs, not with these two.

## Cross-file consistency notes

- `channels.yaml` and `instruments.yaml` consistently use Cyrillic `Т1`..`Т24`.
- `config/interlocks.yaml` patterns are aligned with those canonical names.
- The only committed active mismatch I found is `config/housekeeping.yaml` using Latin `T` in `include_patterns`.
- `config/shifts.yaml` names a pressure alias `"Давление"`, but runtime pressure channels are driver namespaces like `VSP63D_1/pressure`; that key is currently dead anyway.
- `config/plugins.yaml` configures built-in analytics modules, while root `plugins/*.py` are loaded independently with per-file sidecars. The names do not overlap.

## Files audited

- `config/alarms.yaml`
- `config/alarms_v3.yaml`
- `config/channels.yaml`
- `config/cooldown.yaml`
- `config/housekeeping.yaml`
- `config/instruments.yaml`
- `config/instruments.local.yaml.example`
- `config/interlocks.yaml`
- `config/notifications.yaml`
- `config/notifications.local.yaml.example`
- `config/plugins.yaml`
- `config/safety.yaml`
- `config/shifts.yaml`
- `config/experiment_templates/calibration.yaml`
- `config/experiment_templates/cooldown_test.yaml`
- `config/experiment_templates/custom.yaml`
- `config/experiment_templates/debug_checkout.yaml`
- `config/experiment_templates/thermal_conductivity.yaml`
