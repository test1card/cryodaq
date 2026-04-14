# CONFIG_CROSS_REFERENCE.md

**Generated:** 2026-04-14
**Method:** grep for filename references in src/cryodaq/, manual verification of loader functions and error handling
**Scope:** All YAML config files under config/ and config/experiment_templates/

---

## Summary

| Config | Primary reader | Other readers | Error strategy | .local.yaml via _cfg() |
|---|---|---|---|---|
| safety.yaml | safety_manager.py | — | Fail-closed (SafetyConfigError) | YES |
| alarms_v3.yaml | alarm_config.py | housekeeping.py (cross-section) | Fail-closed (AlarmConfigError) | **NO** (hardcoded path) |
| alarms.yaml | alarm.py (legacy) | housekeeping.py (cross-section) | Fail-closed (AlarmEngine) | YES |
| interlocks.yaml | interlock.py | housekeeping.py (cross-section) | Fail-closed (InterlockConfigError) | YES |
| housekeeping.yaml | housekeeping.py | — | Fail-closed (HousekeepingConfigError) | YES |
| channels.yaml | channel_manager.py | channel_editor.py (GUI write-back) | Fail-closed (ChannelConfigError) | **NO** (own path resolver) |
| instruments.yaml | engine.py | calibration_panel.py, connection_settings.py | Implicit fail-closed (driver init) | YES |
| notifications.yaml | telegram.py, engine.py | escalation.py, periodic_report.py, telegram_commands.py (docstring) | Fail-open (missing = disabled) | YES |
| plugins.yaml | engine.py | — | Fail-open (missing = disabled) | YES |
| cooldown.yaml | engine.py | — | Fail-open (missing = disabled) | YES |
| shifts.yaml | shift_handover.py (GUI) | — | Fail-open (missing = disabled) | **NO** (own path resolver) |
| experiment_templates/*.yaml | experiment.py | engine.py (listing) | Fail-closed (ValueError on bad template) | **NO** (directory glob) |

**Legend:**
- **Fail-closed:** Missing or malformed config raises exception that prevents subsystem/engine startup
- **Fail-open:** Missing config silently disables feature with log message
- **Cross-section:** Module reads a specific section of another subsystem's config

---

## _cfg() resolution mechanism

**Location:** `src/cryodaq/engine.py:780-782`

```python
def _cfg(name: str) -> Path:
    local = _CONFIG_DIR / f"{name}.local.yaml"
    return local if local.exists() else _CONFIG_DIR / f"{name}.yaml"
```

**Behavior:** Full file replacement, NOT merge. If `instruments.local.yaml` exists, engine ignores `instruments.yaml` entirely. This is the Codex D.1 finding — a `.local.yaml` must be a **complete** config, not a partial override.

**Configs using _cfg():** instruments, alarms (legacy), interlocks, housekeeping, safety, plugins, notifications, cooldown (8 of 11 base configs)

**Configs NOT using _cfg():**
- `alarms_v3.yaml` — hardcoded `_CONFIG_DIR / "alarms_v3.yaml"` (engine.py:826, 961). No .local variant exists.
- `channels.yaml` — loaded by channel_manager.py via `_get_config_dir() / "channels.yaml"` (line 24). Separate path resolver, no .local support.
- `shifts.yaml` — loaded by shift_handover.py via `_get_config_dir() / "shifts.yaml"` (line 41). GUI-only, no .local support.
- `experiment_templates/` — directory glob via `_CONFIG_DIR / "experiment_templates"` (engine.py:956). Individual templates, not overridable.

---

## .local.yaml files status

**Example files present:**
- `config/instruments.local.yaml.example` — GPIB/USB addresses, COM ports, calibration metadata for FIAN lab
- `config/notifications.local.yaml.example` — Telegram bot_token, chat_ids (security-critical)

**Actual .local.yaml files:** None currently exist in config/. Developer machine has not deployed local overrides.

**Configs with _cfg() support but NO .example file:** alarms (legacy), interlocks, housekeeping, safety, plugins, cooldown (6 configs). Operators would need to create .local.yaml files from scratch without a template.

---

## Detailed per-config analysis

## config/safety.yaml

**Purpose:** SafetyManager FSM configuration — timeouts, rate limits, drain timeout
**Size:** 48 lines
**Primary reader:** `src/cryodaq/core/safety_manager.py:138-214` — `SafetyManager.load_config()`
**Loader function:** `SafetyManager.load_config(path: Path)`
**Error handling:** Fail-closed via `SafetyConfigError` (RuntimeError subclass). Catches: file missing, YAML parse error, non-mapping type, coercion errors on numeric fields (stale_timeout_s, etc.)
**Cross-subsystem usage:** None
**.local.yaml:** Supported via _cfg(). No .example file.

---

## config/alarms_v3.yaml

**Purpose:** V3 alarm engine — temperature limits, rate thresholds, phase-dependent rules, composite conditions
**Size:** 307 lines (largest config)
**Primary reader:** `src/cryodaq/core/alarm_config.py:79-201` — `load_alarm_config()`
**Other readers:**
- `src/cryodaq/core/housekeeping.py:138-217` — `load_critical_channels_from_alarms_v3()` reads `global_alarms`, `phase_alarms`, `interlocks`, `channel_groups` sections to extract critical channel patterns for throttle protection
- `src/cryodaq/engine.py:826-827` — calls `load_critical_channels_from_alarms_v3()` directly

**Loader function:** `load_alarm_config(path: Path) -> (EngineConfig, list[AlarmConfig])`
**Error handling:** Fail-closed via `AlarmConfigError` (RuntimeError subclass) in alarm_config.py. **However:** housekeeping.py:138-217 reads the same file with try/except that returns empty set on failure (fail-tolerant). This is intentional — housekeeping can still function without critical channel patterns, but alarm engine cannot function without alarm rules.

**Cross-subsystem usage:** YES — housekeeping reads alarm config for throttle protection.
This is the Phase 2d A.2 finding: housekeeping.py was reading the `interlocks:` section that CC deleted from alarms_v3.yaml as "dead config". The cross-subsystem reader survived because the section was restored.

**.local.yaml:** NOT supported. Uses hardcoded `_CONFIG_DIR / "alarms_v3.yaml"`. No .example file.

### Section-level readers

| Section | Reader module | Usage |
|---|---|---|
| `global_alarms` | alarm_config.py | Alarm rules for all phases |
| `phase_alarms` | alarm_config.py | Phase-specific alarm rules |
| `interlocks` | alarm_config.py, housekeeping.py | Interlock conditions (dual reader!) |
| `channel_groups` | alarm_config.py, housekeeping.py | Channel groupings for composite alarms |
| `engine` | alarm_config.py | Alarm engine settings (cooldown, retry) |

---

## config/alarms.yaml (legacy)

**Purpose:** Legacy alarm definitions (pre-v2)
**Size:** 58 lines
**Primary reader:** `src/cryodaq/core/alarm.py:193-235` — `AlarmEngine.load_config()`
**Other readers:**
- `src/cryodaq/core/housekeeping.py:47-59` — `load_protected_channel_patterns()` extracts legacy channel_pattern lists
- `src/cryodaq/engine.py:821,825,893` — backward-compatibility merge with interlocks, legacy pattern extraction

**Error handling:** Fail-closed via AlarmEngine.load_config(). Housekeeping reads tolerantly (missing → empty patterns, ERROR log).
**Cross-subsystem usage:** YES — housekeeping reads legacy patterns.
**.local.yaml:** Supported via _cfg(). No .example file.

---

## config/interlocks.yaml

**Purpose:** Interlock conditions and action mappings (legacy format, coexists with alarms_v3 interlocks section)
**Size:** 48 lines
**Primary reader:** `src/cryodaq/core/interlock.py:199-270` — `InterlockEngine.load_config()`
**Other readers:**
- `src/cryodaq/core/housekeeping.py:47-59` — `load_protected_channel_patterns()` extracts legacy patterns
- `src/cryodaq/engine.py:786,821,825,950` — backward-compatibility merge, legacy pattern extraction

**Loader function:** `InterlockEngine.load_config(config_path: Path)`
**Error handling:** Fail-closed via `InterlockConfigError` (RuntimeError subclass). Housekeeping reads tolerantly.
**Cross-subsystem usage:** YES — housekeeping reads patterns; engine merges with alarms.yaml for backward compat.
**.local.yaml:** Supported via _cfg(). No .example file.

---

## config/housekeeping.yaml

**Purpose:** Background maintenance — data throttle, retention, compression
**Size:** 26 lines
**Primary reader:** `src/cryodaq/core/housekeeping.py:25-44` — `load_housekeeping_config()`
**Loader function:** `load_housekeeping_config(config_path: Path) -> dict[str, Any]`
**Error handling:** Fail-closed via `HousekeepingConfigError` (RuntimeError subclass)
**Cross-subsystem usage:** None (housekeeping reads FROM other configs, but nobody reads FROM housekeeping.yaml)
**.local.yaml:** Supported via _cfg(). No .example file.

---

## config/channels.yaml

**Purpose:** Channel display names, units, visibility, groupings
**Size:** 97 lines
**Primary reader:** `src/cryodaq/core/channel_manager.py:24,80-107` — `ChannelManager.load()`
**Other readers:**
- `src/cryodaq/gui/widgets/channel_editor.py` — GUI write-back (edits channel visibility/names and saves back to channels.yaml)

**Loader function:** `ChannelManager.load()` (singleton via `get_channel_manager()`)
**Error handling:** Fail-closed via `ChannelConfigError` (RuntimeError subclass). Catches: file missing, YAML parse error, non-mapping, missing/invalid `channels` key.
**Cross-subsystem usage:** channel_editor.py writes back to the same file (GUI → config round-trip).
**.local.yaml:** NOT supported. Uses own `_get_config_dir() / "channels.yaml"` path. No _cfg() call.

---

## config/instruments.yaml

**Purpose:** GPIB/serial/USB addresses, baud rates, timeouts, calibration metadata
**Size:** 53 lines
**Primary reader:** `src/cryodaq/engine.py:784,800` — `_load_drivers(instruments_cfg, ...)`
**Other readers:**
- `src/cryodaq/gui/widgets/calibration_panel.py:46-71` — `_load_lakeshore_channels()` reads LakeShore channel names
- `src/cryodaq/gui/widgets/connection_settings.py:37-66` — `_DEFAULT_CONFIG` loads for connection editor GUI

**Error handling:** Implicit fail-closed — driver initialization will fail if addresses are wrong/missing. No explicit ConfigError class.
**Cross-subsystem usage:** YES — GUI calibration and connection settings panels read instruments config directly.
**.local.yaml:** Supported via _cfg(). Has .example file with full FIAN lab setup.

---

## config/notifications.yaml

**Purpose:** Telegram bot_token, chat_ids, escalation chain, periodic report schedule
**Size:** 19 lines
**Primary reader:** `src/cryodaq/engine.py:1351-1402` — conditional loading and notifier setup
**Other readers:**
- `src/cryodaq/notifications/telegram.py:87-122` — `TelegramNotifier.from_config()`
- `src/cryodaq/notifications/escalation.py:6` — docstring reference
- `src/cryodaq/notifications/periodic_report.py:6` — docstring reference
- `src/cryodaq/notifications/telegram_commands.py:95` — error message reference

**Error handling:** Fail-open — missing file silently disables all notification features. BUT: if `commands.enabled: true` and `allowed_chat_ids` is empty, engine logs ERROR and refuses to start TelegramCommandBot (partial fail-closed for security).
**Cross-subsystem usage:** Engine orchestrates all notification subsystems from one config.
**.local.yaml:** Supported via _cfg(). Has .example file (security-critical: contains bot_token template).

---

## config/plugins.yaml

**Purpose:** Feature flags and parameters for sensor_diagnostics and vacuum_trend
**Size:** 38 lines
**Primary reader:** `src/cryodaq/engine.py:985-1019` — conditional feature setup
**Loader function:** None dedicated — engine reads with `yaml.safe_load()` inline
**Error handling:** Fail-open — missing or malformed file disables both features with INFO log.
**Cross-subsystem usage:** None
**.local.yaml:** Supported via _cfg(). No .example file.

---

## config/cooldown.yaml

**Purpose:** Cooldown predictor model parameters — model directory, update interval
**Size:** 15 lines
**Primary reader:** `src/cryodaq/engine.py:1330-1341` — conditional cooldown service setup
**Error handling:** Fail-open — missing file silently disables cooldown prediction.
**Cross-subsystem usage:** None
**.local.yaml:** Supported via _cfg(). No .example file.

---

## config/shifts.yaml

**Purpose:** Shift definitions and labels for operator shift tracking
**Size:** 12 lines
**Primary reader:** `src/cryodaq/gui/widgets/shift_handover.py:41-75` — `load_shift_config()`
**Error handling:** Fail-open — missing file disables shift tracking (GUI opt-in feature).
**Cross-subsystem usage:** None. Loaded by GUI only, not by engine.
**.local.yaml:** NOT supported. Uses own `_get_config_dir() / "shifts.yaml"`. Not loaded via engine _cfg().

---

## config/experiment_templates/*.yaml

**Purpose:** Pre-defined experiment types (cooldown_test, calibration, thermal_conductivity, debug_checkout, custom)
**Size:** 5 files, 91 lines total
**Primary reader:** `src/cryodaq/core/experiment.py:933-976` — `ExperimentManager._load_templates()` via glob
**Other readers:**
- `src/cryodaq/engine.py:402,956` — lists templates for command handler

**Error handling:** Fail-closed per template — ValueError if template missing `id` field. Fallback: if no `custom` template found, creates default in-memory.
**Cross-subsystem usage:** None
**.local.yaml:** Not applicable (directory of individual templates, not a single config).

---

## Cross-subsystem reading map

```
housekeeping.py ──reads─→ alarms.yaml (legacy patterns)
                ──reads─→ interlocks.yaml (legacy patterns)
                ──reads─→ alarms_v3.yaml (critical channels: global_alarms, phase_alarms, interlocks, channel_groups)

engine.py ──orchestrates─→ alarms.yaml + interlocks.yaml (backward-compat merge for legacy AlarmEngine)
          ──orchestrates─→ alarms_v3.yaml (AlarmV2 engine + critical channels for housekeeping)
          ──orchestrates─→ notifications.yaml (telegram + escalation + periodic_report + commands)
          ──orchestrates─→ plugins.yaml (sensor_diagnostics + vacuum_trend)

calibration_panel.py ──reads─→ instruments.yaml (LakeShore channel names)
connection_settings.py ──reads─→ instruments.yaml (addresses for editor)
channel_editor.py ──writes─→ channels.yaml (GUI write-back)
```

---

## Inconsistent failure discipline

| Config | Loader error strategy | Cross-reader error strategy | Consistent? |
|---|---|---|---|
| alarms_v3.yaml | Fail-closed (AlarmConfigError) | Fail-tolerant (housekeeping returns empty set) | **INCONSISTENT** (by design — housekeeping can degrade gracefully) |
| alarms.yaml | Fail-closed (AlarmEngine) | Fail-tolerant (housekeeping returns empty patterns) | **INCONSISTENT** (same design rationale) |
| interlocks.yaml | Fail-closed (InterlockConfigError) | Fail-tolerant (housekeeping returns empty patterns) | **INCONSISTENT** (same design rationale) |

All three inconsistencies are **intentional**: housekeeping's pattern extraction is best-effort — if it can't read alarm/interlock patterns, it simply won't protect those channels from throttling, which is a degraded but safe state. The primary loaders (alarm engine, interlock engine) remain fail-closed.

---

## Orphan configs

None found. All 11 base configs and 5 experiment templates have at least one reader in src/cryodaq/.

---

## Key findings

1. **alarms_v3.yaml is the only multi-reader hotspot** — primary load by alarm_config.py + cross-section read by housekeeping.py. The interlocks section has dual readers (alarm_config + housekeeping). This was the root cause of the Phase 2d A.2 incident.

2. **_cfg() replacement semantics** — .local.yaml is a full replacement, not a merge. Operators must duplicate the entire config file for any local override. This affects 8 of 11 base configs. Phase 2e candidate CONFIG_AUDIT C.1 proposes merge behavior instead.

3. **3 configs lack .local.yaml support** — alarms_v3.yaml, channels.yaml, shifts.yaml use their own path resolvers and bypass engine's _cfg(). If operators need per-machine variants of these configs, they currently cannot get them without code changes.

4. **GUI-loaded configs (2)** — channels.yaml (channel_manager) and shifts.yaml (shift_handover) are loaded by GUI modules directly, not by engine. They use `_get_config_dir()` which resolves to the same config/ directory but doesn't check for .local.yaml.

5. **instruments.yaml is security-critical for deployment** — it's the only config with both an .example file AND cross-subsystem GUI readers. Three different modules load it for different purposes (engine for drivers, calibration_panel for channel names, connection_settings for address editing).

6. **6 _cfg()-enabled configs have no .example file** — operators would need to create .local.yaml from scratch for alarms (legacy), interlocks, housekeeping, safety, plugins, cooldown.
