# Analytics tab — operator guide

## Phase-gated widget layout

The Analytics tab shows different widgets depending on the current experiment phase.
Each phase shows up to 3 widgets (main slot + two side slots):

| Phase | Main (½ screen) | Top right (¼) | Bottom right (¼) |
|---|---|---|---|
| preparation | Temperature channels | Pressure | Sensor health |
| vacuum | Vacuum projection | Temperature channels | Pressure |
| cooldown | Cooldown trajectory | Temperature channels | R_thermal (F8) |
| measurement | R_thermal (live) | Temperature channels | Keithley power |
| warmup | Temperature history | Pressure | Past cooldowns |
| disassembly | Experiment summary | — | — |
| (no experiment) | Temperature channels | Pressure | Sensor health |

## Plot-by-plot behavior

### Cooldown trajectory (cooldown phase, main slot)

Shows the predicted cooldown trajectory (T_cold vs time) with a confidence band,
rendered only when the system is actively cooling.

**Empty / no overlay:** The prediction requires T_cold to be dropping at
>5 K/h for at least 10 consecutive minutes (`CooldownDetector` confirmation window).
The widget shows "Охлаждение не активно — прогноз недоступен" when:
- System is at base temperature (T_cold ≈ 4 K) — physically at steady state
- System has not started cooling yet (operator advanced to cooldown phase before
  turning on the cryocooler)
- Cooling rate < 5 K/h (early warmup or slow start)

This is **expected behavior**. The prediction will appear automatically once
the detector confirms active cooldown.

### Vacuum projection (vacuum phase, main slot)

Shows projected pressure P(t) with ±1σ confidence band from the vacuum trend predictor.

**Empty / no overlay:** Requires at least 60 pressure readings accumulated in the
predictor buffer. Empty on first open; populates within ~10 minutes of pumping.

**Not visible in other phases:** Vacuum projection is only mounted during the vacuum
phase. If you see an empty area where you expect it — check the current experiment phase.

### Temperature channels (every phase, top right slot)

Shows live temperature readings from all configured LakeShore 218S channels.

**Empty on first open:** This widget receives live readings from the broker; it does
not pre-fetch historical data. The first reading arrives within one poll cycle
(typically 2s after opening the tab). The "Ожидание данных…" placeholder is shown
until the first reading arrives.

### R_thermal (measurement phase, main slot)

Shows live thermal resistance R_thermal with a SteadyStatePredictor asymptote overlay.

**Asymptote overlay:** Appears once the predictor has ≥30% convergence (typically
several minutes after entering measurement phase). The dashed line shows the predicted
R_thermal steady-state value.

**"данные источника ожидают (зависит от F8)" (cooldown phase):** In cooldown phase,
the bottom-right slot shows the R_thermal placeholder. F8 = cooldown ML upgrade
(research feature, not yet implemented). This text is expected.

### Experiment summary (disassembly phase, main slot)

Shows experiment duration, phase breakdown, channel statistics, alarm count, and
artifact links. Populated on enter of disassembly phase.

## Common questions

**"All plots empty on the Analytics tab"**

Most common cause: the experiment is in a phase where predictions have no data yet.

Check list:
1. What is the current experiment phase? (shown in the experiment overlay)
2. Is the system at base temperature? (T_cold ≈ 4K → cooldown trajectory empty = expected)
3. Did you just open the Analytics tab? (temperature channels fill within 2s)
4. Is the cryocooler actually running? (cooldown trajectory needs active cooling)

**"Vacuum projection not showing"**

Vacuum projection is only shown during the `vacuum` phase. If you're in cooldown or
measurement phase, this widget is not mounted. Use the Аналитика → vacuum phase
to see vacuum projection.

**"Temperature channels empty for a long time"**

If "Ожидание данных…" persists >5 seconds, the engine may not be publishing or the
ZMQ bridge may need a restart. Check the connection indicator in the status bar.
