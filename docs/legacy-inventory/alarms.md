# Legacy Alarms Panel Feature Inventory

## File overview
- File: `src/cryodaq/gui/widgets/alarm_panel.py`
- Total lines: 378
- Major sections:
  - Lines 1-70: imports, severity colors/icons/order, column defs, _AlarmRow dataclass
  - Lines 87-118: AlarmPanel init, v1+v2 alarm dicts, v2 poll timer (3s)
  - Lines 120-160: _build_ui (v1 table + v2 table)
  - Lines 166-278: v1 alarm handling (on_reading → _handle_reading → _refresh_table)
  - Lines 279-292: v1 acknowledge (ZMQ alarm_acknowledge)
  - Lines 297-378: v2 alarm polling + table + acknowledge (alarm_v2_status, alarm_v2_ack)

## Layout structure

```
AlarmPanel: QVBoxLayout
  v1 alarm table: QTableWidget
    Columns: Уровень | Имя | Канал | Значение | Порог | Время | Срабат. | Действие
    Sorted by severity (CRITICAL → WARNING → INFO)
    Each row: color-coded by severity, "Подтвердить" button if active
  
  v2 label: "Алармы v2 (физические)"
  
  v2 alarm table: QTableWidget (max height 200px)
    Columns: Уровень | Alarm ID | Сообщение | Каналы | Время | Действие
    Each row: "ACK" button, severity-colored
```

## Two alarm engines

**v1 (legacy AlarmEngine):**
- Via on_reading — alarm events arrive as Reading metadata
- Alarm states: ok / active / acknowledged / cleared
- Event types: activated / acknowledged / cleared
- Table shows: severity icon, name, channel, value, threshold, elapsed time, trigger count
- Acknowledge: sends `alarm_acknowledge` ZMQ command

**v2 (AlarmEngine v2 — physical alarms):**
- Via 3-second polling: `alarm_v2_status` ZMQ command
- Shows active v2 alarms with level, ID, message, channels, elapsed time
- Acknowledge: sends `alarm_v2_ack` ZMQ command
- Emits `v2_alarm_count_changed(int)` signal → TopWatchBar alarm badge

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `alarm_acknowledge` | `{cmd, alarm_name: str}` | v1 "Подтвердить" button click |
| `alarm_v2_status` | `{cmd}` | 3-second poll timer |
| `alarm_v2_ack` | `{cmd, alarm_name: str}` | v2 "ACK" button click |

## Live data subscriptions

- Any reading with `metadata.alarm_name` set → v1 alarm table update
- Channel pattern: `alarm/*` (implicit — AlarmEngine sends on matching channels)

## Signals / slots

- `v2_alarm_count_changed(int)` — public signal connected to TopWatchBar alarm badge
- `_reading_signal` — internal thread-safe Signal for on_reading

## Operator workflows

1. **Check active alarms** — scan v1 + v2 tables for red/yellow rows
2. **Acknowledge alarm** — click "Подтвердить" (v1) or "ACK" (v2) button
3. **Monitor alarm history** — view trigger count + elapsed time per alarm
4. **Assess severity** — CRITICAL sorted to top, visual icon (🔴🟡🔵)

## Comparison: legacy vs new (P2 — alarms could be missed)

| Feature | Legacy | New | Status |
|---------|--------|-----|--------|
| Alarm count badge | Not in tab (user must switch to see) | TopWatchBar zone 4 alarm badge | ✓ COVERED (P2 solved) |
| v1 alarm table | Full table with all columns | Not in new overlay | ✗ NOT COVERED |
| v2 alarm table | Full table with ACK buttons | Not in new overlay | ✗ NOT COVERED |
| Acknowledge v1 | "Подтвердить" button per alarm | Not accessible from dashboard | ✗ NOT COVERED |
| Acknowledge v2 | "ACK" button per alarm | Not accessible from dashboard | ✗ NOT COVERED |
| Severity sorting | CRITICAL → WARNING → INFO | TopWatchBar shows count only | ⚠ PARTIAL |

## Recommendations for Phase II overlay rebuild

**MUST preserve:**
- Both v1 and v2 alarm tables (dual engine support)
- Acknowledge workflow for both engines (one-click acknowledge per alarm)
- Severity-based sorting (CRITICAL first)
- Severity color coding (red/yellow/blue) with text labels (not color-only)
- v2_alarm_count_changed signal for TopWatchBar badge
- Trigger count + elapsed time display

**COULD defer:**
- Alarm rule editing (not in current panel — would be new feature)
- Alarm history persistence (current = session-only for v1)
- Filter/search by alarm name or channel

**SHOULD cut:**
- Emoji icons (🔴🟡🔵) — replace with theme-colored dots or text per design system
- Hardcoded severity colors (use theme.STATUS_* tokens)
- 200px max height on v2 table (use proportional sizing)

P2 (alarms could be missed) is already PARTIALLY solved by TopWatchBar
badge. Full solution requires this alarm overlay to be accessible via
badge click for acknowledge workflow. Panel itself is structurally
simple — two tables with acknowledge buttons. Rebuild is primarily
visual modernization + badge click → overlay integration.
