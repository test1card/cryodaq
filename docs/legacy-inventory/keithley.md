# Legacy Keithley Panel Feature Inventory

## File overview
- File: `src/cryodaq/gui/widgets/keithley_panel.py`
- Total lines: 586
- Major sections:
  - Lines 1-62: imports, constants, color maps per measurement
  - Lines 64-530: `_SmuPanel` — single SMU channel panel
  - Lines 530-586: `KeithleyPanel` — dual-SMU container

## Layout structure

```
KeithleyPanel: QVBoxLayout
  Header action row:
    [Старт A+B] [Стоп A+B] [АВАР. ОТКЛ. A+B]
  QHBoxLayout (two equal columns):
    _SmuPanel("smua")
    _SmuPanel("smub")

_SmuPanel: QVBoxLayout (per channel)
  Header: HBox
    [Канал A (smua)] [stretch] [state: ВЫКЛ/ВКЛ/АВАРИЯ]
  
  Controls: QWidget (panel frame)
    HBox:
      [P цель (Вт): QDoubleSpinBox(0-10, step=0.1, default=0.5)]
      [V предел (В): QDoubleSpinBox(0-200, step=1, default=40)]
      [I предел (А): QDoubleSpinBox(0-3, step=0.1, default=1)]
      [stretch]
      [QPushButton "Старт" (green)]
      [QPushButton "Стоп" (amber)]
      [QPushButton "АВАР. ОТКЛ." (red, bold)]
  
  Status banner
  
  Readouts: HBox (4 big value labels)
    [Напряжение (В)] [Ток (А)] [Сопротивление (Ом)] [Мощность (Вт)]
    Each: value (24px mono bold) + unit label below
  
  Plots: QGridLayout (2x2)
    [Voltage plot] [Current plot]
    [Resistance plot] [Power plot]
    Each: pyqtgraph PlotWidget, rolling time window, quantity-colored line
```

## Input controls

| Control | Type | Default | Range | Validation | Debounce |
|---------|------|---------|-------|------------|----------|
| P цель (Вт) | QDoubleSpinBox | 0.5 | 0-10 | step=0.1, decimals=3 | 300ms |
| V предел (В) | QDoubleSpinBox | 40.0 | 0-200 | step=1, decimals=2 | 300ms |
| I предел (А) | QDoubleSpinBox | 1.0 | 0-3 | step=0.1, decimals=3 | 300ms |
| Старт | QPushButton | — | — | Disables during in-flight | — |
| Стоп | QPushButton | — | — | Disables during in-flight | — |
| АВАР. ОТКЛ. | QPushButton | — | — | Always enabled | — |

P target and limits are debounced (300ms QTimer) — operator can spin
without flooding backend with commands.

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `keithley_start` | `{cmd, channel: "smua"/"smub", target_power: float, voltage_limit: float, current_limit: float}` | Старт button |
| `keithley_stop` | `{cmd, channel: "smua"/"smub"}` | Стоп button |
| `keithley_emergency_off` | `{cmd, channel: "smua"/"smub"}` | АВАР. ОТКЛ. button |
| `keithley_set_target` | `{cmd, channel, target_power}` | P spin (debounced 300ms) |
| `keithley_set_limits` | `{cmd, channel, voltage_limit, current_limit}` | V/I spin (debounced 300ms) |

## Live data subscriptions

- `Keithley_*/smua/voltage` → voltage buffer + readout
- `Keithley_*/smua/current` → current buffer + readout
- `Keithley_*/smua/resistance` → resistance buffer + readout
- `Keithley_*/smua/power` → power buffer + readout
- Same for `/smub/*`
- `analytics/keithley_channel_state/smua` → state label (off/on/fault)
- `analytics/keithley_channel_state/smub` → state label

## Dual-channel architecture

Two independent `_SmuPanel` instances side-by-side. Each has:
- Own set of controls (P/V/I spinboxes + Start/Stop/Emergency)
- Own 4 readout labels (V/I/R/P)
- Own 4 rolling plots (V/I/R/P over time)
- Own ZMQ commands scoped to "smua" or "smub"
- Own state tracking (off/on/fault) from analytics channel

Panel-level combined actions also exist in `KeithleyPanel` itself:
- `Старт A+B` → dispatches `_on_start()` to both `_SmuPanel` instances
- `Стоп A+B` → dispatches `_on_stop()` to both `_SmuPanel` instances
- `АВАР. ОТКЛ. A+B` → dispatches `_on_emergency()` to both `_SmuPanel` instances

FYI: a previous version of this inventory documented the panel as per-channel
only. That claim does not match source as of `cf72942`.

## Operator workflows

1. **Start channel** — set P target, verify V/I limits, click Старт, watch readouts go live
2. **Adjust power** — spin P цель while running, backend adjusts (debounced)
3. **Monitor V/I/R/P** — watch 4 rolling plots for stability
4. **Emergency off** — click АВАР. ОТКЛ., immediate backend response
5. **Compare A vs B** — both panels visible simultaneously, visual comparison
6. **Drive both channels together** — use Старт A+B / Стоп A+B / АВАР. ОТКЛ. A+B from the panel header

## Recommendations for Phase II overlay rebuild

**MUST preserve (K4 — direct Keithley control):**
- Dual-channel layout (smua + smub side-by-side)
- Panel-level A+B controls in addition to per-channel controls
- P target spinbox with live adjustment (debounced)
- V and I limit spinboxes
- Start / Stop / Emergency Off buttons per channel
- 4 readout values per channel (V/I/R/P with quantity color coding)
- 4 rolling plots per channel (V/I/R/P over time)
- State indicator per channel (ВЫКЛ/ВКЛ/АВАРИЯ)
- Emergency off always enabled regardless of state

**COULD defer:**
- Custom command field (K4 mentions custom commands, not in current panel)
- Plot time window customization (currently uses fixed 10-minute window)

**SHOULD cut:**
- Hardcoded color hex in button styles (use theme tokens)
- Fixed 10px/8px margins (use theme.SPACE_* tokens)
- Panel-level redundant status banner (TopWatchBar covers)

This panel is functionally complete and has no missing features.
Rebuild is purely a visual modernization pass with theme tokens.

## Preserve-feature appendix

This inventory anchors the following K# preserve features (per `docs/phase-ui-1/ui_refactor_context.md` §3):

- K4: direct Keithley control via per-channel `Старт` / `Стоп` / `АВАР. ОТКЛ.` controls and live `keithley_set_target` / `keithley_set_limits` updates (`keithley_panel.py:117-160`, `keithley_panel.py:322-434`)
- K4: combined A+B control surface in `KeithleyPanel` header (`keithley_panel.py:489-555`)
- K5: per-channel rolling V/I/R/P plots (`keithley_panel.py:162-277`, `keithley_panel.py:457-476`)

Verified anchors: K4, K5
NOT anchored by this inventory: K1, K2, K3, K6, K7

---
*Coverage claims in this inventory verified against new-shell code at commit `cf72942` (date 2026-04-16). Re-verify before treating as authoritative for Phase II rebuilds.*
