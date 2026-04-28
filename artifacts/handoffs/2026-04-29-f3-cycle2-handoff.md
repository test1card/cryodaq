# F3 Cycle 2 (W1 temperature_trajectory) — architect review

## Status
COMPLETE-PASSED (pending audit results)

## Branch
feat/f3-cycle2-temperature-trajectory at b30515a
Pushed: yes
Merged: NO — architect reviews in morning per runner §1

## Tests
14 new (test_analytics_widget_temperature_trajectory.py) + updated test_analytics_widgets.py
1859 / 1860 green at final commit
Pre-existing tests: regression count = 0
Failing tests: test_format_time_same_day_returns_hh_mm (pre-existing timezone-drift, unrelated)

## Implementation summary

### What changed

**src/cryodaq/gui/shell/views/analytics_widgets.py** (new class + registration change)
- Added imports: `Slot` from PySide6.QtCore, `get_channel_manager` from core
- Added `TemperatureTrajectoryWidget` class (~100 LOC):
  - Construction: `_fetch_history()` creates ZmqCommandWorker (readings_history, 7-day, 5000 pts/ch)
  - `_on_history_loaded(result)`: merges engine history into _series
  - `set_temperature_readings(readings)`: live append, trims at 5000 pts
  - `_update_empty_state()`: toggles empty label / plot visibility via setHidden()
  - `_update_curve()`: pyqtgraph per-channel curve with channel_manager display name
- Changed: `register(WIDGET_TEMPERATURE_TRAJECTORY, TemperatureTrajectoryWidget)` (was placeholder)

**src/cryodaq/gui/shell/main_window_v2.py** (+7 LOC)
- Added after existing calibration routing:
  `if reading.unit == "K":` → update `_analytics_temperature_snapshot[channel]` + forward to view

**tests/gui/shell/views/test_analytics_widgets.py** (updated)
- Removed `temperature_trajectory` from placeholder parametrize
- Added `test_temperature_trajectory_is_real_widget_not_placeholder`

**tests/gui/shell/views/test_analytics_widget_temperature_trajectory.py** (new, +266 LOC)
- 14 tests per spec §4.1 acceptance criteria

### Spec deviations
- Time window: 7-day lookback used instead of "full experiment from start to now"
  **Reason:** experiment start timestamp requires `set_experiment_status` setter which is
  Cycle 4 work. 7-day window is generous enough to cover any experiment duration.
  **ARCHITECT DECISION NEEDED:** Is 7-day window acceptable, or should experiment start
  time be passed to widget differently (before Cycle 4)?
- Channel selection: all visible channels from channel_manager used (not filtered by unit=="K")
  since channel_manager doesn't track units. Relies on engine returning only channels with data.

## Architect decisions needed (morning)
1. **7-day lookback vs experiment start time**: The widget uses a 7-day lookback for
   readings_history fetch because experiment start_ts is not yet accessible in the
   analytics widget layer. If exact experiment-start-time boundary is important before
   Cycle 4, I need to either (a) add a lightweight `set_experiment_start_ts(float)` setter
   now, or (b) accept 7-day as the F3 approximation.
2. **Cycle 2 merge order**: Cycle 2 depends on Cycle 1 (already merged). No inter-dependency
   with Cycles 3-4. Safe to merge after architect review.

## Files changed
| File | LOC delta | Notes |
|---|---|---|
| src/cryodaq/gui/shell/views/analytics_widgets.py | +113 / -1 | New widget class |
| src/cryodaq/gui/shell/main_window_v2.py | +7 | Temperature routing |
| tests/gui/shell/views/test_analytics_widget_temperature_trajectory.py | +266 | New tests |
| tests/gui/shell/views/test_analytics_widgets.py | +18 / -5 | Updated placeholder test |

## Commits on branch
| SHA | Subject |
|---|---|
| b30515a | feat(analytics): W1 temperature_trajectory widget wired (F3-Cycle2) |
