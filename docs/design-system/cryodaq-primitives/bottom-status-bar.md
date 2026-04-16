---
title: BottomStatusBar
keywords: status-bar, bottom-bar, connection, engine, safety-state, fsm, heartbeat, time
applies_to: bottom chrome strip showing system-level status
status: active
implements: src/cryodaq/gui/shell/bottom_status_bar.py
last_updated: 2026-04-17
references: rules/color-rules.md, rules/data-display-rules.md, rules/content-voice-rules.md
---

# BottomStatusBar

Thin chrome strip at the bottom of every screen. Shows system-level status: engine connection, safety FSM state, ZMQ heartbeat, timestamp. Low-priority information; operator rarely looks at it unless something is wrong.

**When to use:**
- Singleton in `MainWindow`, always visible at bottom
- Any system-level info that should be reachable at a glance but doesn't warrant top-bar prominence

**When NOT to use:**
- High-priority alerts — use `TopWatchBar` vitals or alarm badge
- Per-panel status — panel has its own footer
- Operator action feedback — use `Toast`

## Anatomy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ● Engine: connected    ● Safety: running    ● ZMQ: 0.5с    14:32:15 UTC+3 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
  ◀── height: BOTTOM_BAR_HEIGHT (28)
  ◀── background: SURFACE_CARD
  ◀── border-top: 1px BORDER
  ◀── padding-left aligns with TOOL_RAIL_WIDTH (56)
  ◀── 3 status items left-aligned + timestamp right-aligned
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Bar frame** | Yes | Horizontal strip, `BOTTOM_BAR_HEIGHT` (28) tall |
| **Engine indicator** | Yes | Dot + label: «Engine: connected / disconnected» |
| **Safety FSM indicator** | Yes | Dot + label: current FSM state (safe_off / ready / run_permitted / running / fault_latched) |
| **ZMQ heartbeat** | Yes | Dot + label showing last heartbeat interval |
| **Timestamp** | Yes | Right-aligned, local time + UTC offset |

## Invariants

1. **Height = BOTTOM_BAR_HEIGHT (28).** Smaller than TopWatchBar because lower priority. (RULE-SPACE-007 exception for chrome)
2. **Padding-left aligns with TOOL_RAIL_WIDTH.** Content starts past the rail.
3. **Safety state lowercase.** Display «safe_off», «fault_latched» — matches engine's internal representation. (Per CryoDAQ absolute rule from CLAUDE.md)
4. **Instant fault state rendering.** (RULE-INTER-006)
5. **Stale indicator when heartbeat late.** If ZMQ heartbeat > stale_timeout, mark as stale — critical operator info.
6. **Text is sentence case with colon separator.** «Engine: connected» not «ENGINE: CONNECTED» or «engine connected». Status labels are data readouts, not category headers.
7. **Timestamp uses FONT_MONO.** Prevents visual jitter as seconds tick. (RULE-TYPO-003)
8. **Font sizes small but readable.** `FONT_LABEL_SIZE` (12) works; `FONT_SIZE_XS` (11) in extreme compact.
9. **Each status item has dot + label.** Two redundant channels — color (status) + text. (RULE-A11Y-002)
10. **Not interactive by default.** Clicking status items does nothing. Hover may show tooltip with detail.

## Status labels (Russian operator text)

| Item | Display | Status key | Color |
|---|---|---|---|
| Engine | «Engine: подключён» / «Engine: нет связи» / «Engine: запуск» | connected / disconnected / connecting | OK / FAULT / WARNING |
| Safety FSM | «Safety: safe_off» / «Safety: ready» / «Safety: run_permitted» / «Safety: running» / «Safety: fault_latched» | matches FSM state | STATUS_* matching state |
| ZMQ | «ZMQ: 0.5с» / «ZMQ: 12с · нет связи» | interval; stale marker | OK if < threshold, STATUS_STALE if exceeded |
| Time | «14:32:15 UTC+3» | — | FOREGROUND |

**Note on Engine label:** «Engine» stays in Latin — it's the subsystem name, not operator-facing vocabulary (RULE-COPY-002 exception for subsystem names). `safe_off` / `fault_latched` also stay in code form — these are precise FSM state IDs that operators recognize from logs.

## Safety state → color mapping

| FSM state | Color | Meaning |
|---|---|---|
| `safe_off` | STATUS_STALE (neutral) | Default — nothing running |
| `ready` | STATUS_INFO | Preconditions met, awaiting command |
| `run_permitted` | STATUS_INFO | Authorized to run, awaiting start |
| `running` | STATUS_OK | Active operation |
| `fault_latched` | STATUS_FAULT | Fault; operator must acknowledge |

## API

```python
# src/cryodaq/gui/shell/bottom_status_bar.py

class StatusItem(QWidget):
    """One status item: dot + label."""
    
    def __init__(
        self,
        key: str,
        initial_label: str = "—",
        parent: QWidget | None = None,
    ) -> None: ...
    
    def set(self, label: str, status: str = "ok") -> None:
        """Update label text and status color."""


class BottomStatusBar(QWidget):
    """Bottom chrome strip showing system status."""
    
    def __init__(self, parent: QWidget) -> None: ...
    
    def set_engine(self, state: str) -> None:
        """state: 'connected' | 'disconnected' | 'connecting'."""
    
    def set_safety(self, fsm_state: str) -> None:
        """fsm_state matches one of safe_off / ready / run_permitted / running / fault_latched."""
    
    def set_heartbeat(self, interval_s: float, stale: bool = False) -> None: ...
    
    def set_time(self, t: datetime) -> None:
        """Update displayed timestamp."""
```

## Reference: StatusItem

```python
class StatusItem(QWidget):
    def __init__(self, key: str, initial_label: str = "—", parent=None):
        super().__init__(parent)
        self._key = key
        
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_1)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        # DESIGN: RULE-A11Y-002 — dot + label = redundant channels
        self._dot = QFrame()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(f"""
            QFrame {{
                background: {theme.STATUS_STALE};
                border-radius: 4px;
            }}
        """)
        row.addWidget(self._dot)
        
        self._label = QLabel(initial_label)
        font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        self._label.setFont(font)
        self._label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        row.addWidget(self._label)
    
    def set(self, label: str, status: str = "ok") -> None:
        self._label.setText(label)
        
        color = {
            "ok":      theme.STATUS_OK,
            "info":    theme.STATUS_INFO,
            "warning": theme.STATUS_WARNING,
            "caution": theme.STATUS_CAUTION,
            "fault":   theme.STATUS_FAULT,
            "stale":   theme.STATUS_STALE,
        }.get(status, theme.STATUS_STALE)
        
        # Color the dot only; label stays MUTED_FOREGROUND for readability
        # DESIGN: RULE-A11Y-003 — STATUS_FAULT fails body contrast (3.94:1);
        # so label text stays MUTED_FOREGROUND (passes AA) and dot carries color.
        self._dot.setStyleSheet(f"""
            QFrame {{
                background: {color};
                border-radius: 4px;
            }}
        """)
```

## Reference: BottomStatusBar

```python
class BottomStatusBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(theme.BOTTOM_BAR_HEIGHT)
        self.setObjectName("bottomStatusBar")
        self.setStyleSheet(f"""
            #bottomStatusBar {{
                background: {theme.SURFACE_CARD};
                border: none;
                border-top: 1px solid {theme.BORDER};
            }}
        """)
        
        row = QHBoxLayout(self)
        row.setContentsMargins(
            theme.TOOL_RAIL_WIDTH + theme.SPACE_5,
            0,
            theme.SPACE_5,
            0,
        )
        row.setSpacing(theme.SPACE_5)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        self._engine = StatusItem("engine", "Engine: —")
        self._safety = StatusItem("safety", "Safety: —")
        self._heartbeat = StatusItem("zmq", "ZMQ: —")
        
        row.addWidget(self._engine)
        row.addWidget(self._safety)
        row.addWidget(self._heartbeat)
        row.addStretch()
        
        # DESIGN: RULE-TYPO-003 — tabular numbers for time
        self._time = QLabel("—")
        time_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        time_font.setFeature("tnum", 1)
        time_font.setFeature("liga", 0)
        self._time.setFont(time_font)
        self._time.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        row.addWidget(self._time)
    
    def set_engine(self, state: str) -> None:
        configs = {
            "connected":    ("Engine: подключён", "ok"),
            "disconnected": ("Engine: нет связи", "fault"),
            "connecting":   ("Engine: запуск",    "warning"),
        }
        label, status = configs.get(state, (f"Engine: {state}", "stale"))
        self._engine.set(label, status)
    
    def set_safety(self, fsm_state: str) -> None:
        # DESIGN: absolute rule — FSM states lowercase
        status = {
            "safe_off":       "stale",
            "ready":          "info",
            "run_permitted":  "info",
            "running":        "ok",
            "fault_latched":  "fault",
        }.get(fsm_state, "stale")
        self._safety.set(f"Safety: {fsm_state}", status)
    
    def set_heartbeat(self, interval_s: float, stale: bool = False) -> None:
        if stale:
            self._heartbeat.set(f"ZMQ: {interval_s:.1f}с · нет связи", "stale")
        elif interval_s > 2.0:
            self._heartbeat.set(f"ZMQ: {interval_s:.1f}с", "warning")
        else:
            self._heartbeat.set(f"ZMQ: {interval_s:.1f}с", "ok")
    
    def set_time(self, t: datetime) -> None:
        # DESIGN: RULE-COPY-008 (point decimal default), monospace digits
        # Display: "14:32:15 UTC+3"
        offset = t.utcoffset()
        offset_hours = int(offset.total_seconds() / 3600) if offset else 0
        self._time.setText(f"{t.strftime('%H:%M:%S')} UTC{offset_hours:+d}")
```

## States

| Bar state | Treatment |
|---|---|
| **Everything OK** | All dots OK color, labels MUTED text |
| **Engine down** | Engine dot FAULT (red); other items likely also fault or stale |
| **Fault latched** | Safety dot FAULT red; label «Safety: fault_latched»; operator attention required |
| **Stale heartbeat** | ZMQ dot STATUS_STALE; indicates engine process alive but not publishing |
| **Time lost** | If system clock can't be read, show «—» instead of time |

## Stale ZMQ vs disconnected engine

These are different failure modes:
- **Disconnected engine** = ZMQ socket can't connect at all; bar shows both Engine: disconnected AND ZMQ: stale.
- **Stale ZMQ** = socket connected but no messages arriving. Engine process may be deadlocked or frozen. Bar shows Engine: connected BUT ZMQ stale. This is an important diagnostic signal that should not be hidden.

## Common mistakes

1. **Uppercase FSM states.** «SAFE_OFF», «FAULT_LATCHED» — violates absolute codebase rule (lowercase). Display as `safe_off`, `fault_latched`.

2. **Merging dot + colored text.** Putting status color on label text. STATUS_FAULT text fails AA contrast (3.94:1) at body size. Keep text MUTED_FOREGROUND; color the dot. RULE-A11Y-003.

3. **Proportional font on timestamp.** Clock digits shift as seconds tick. Use FONT_MONO. RULE-TYPO-003.

4. **Bar too tall.** Matching HEADER_HEIGHT (56). Bottom bar is lower priority; 28-32 is correct. Oversized bottom bar steals content space.

5. **Missing timestamp timezone.** Just «14:32:15» ambiguous. Include UTC offset or explicit TZ.

6. **Translating Engine / ZMQ / Safety.** These are subsystem names (domain vocabulary). Stay in Latin. Per RULE-COPY-002 exception.

7. **No indication when bar itself becomes stale.** If the GUI process can't reach the engine at all, bar should make this prominent — not just one dot, all items → stale, plus maybe red border-top.

8. **Bar content animating / moving.** Values update in place, no animation. RULE-DATA-001, RULE-INTER-006.

## Related components

- `cryodaq-primitives/top-watch-bar.md` — High-priority vitals counterpart
- `cryodaq-primitives/tool-rail.md` — Left navigation chrome
- `cryodaq-primitives/alarm-badge.md` — Alarm indicator (lives in top area, not bottom)
- `components/toast.md` — Transient notifications (complement to persistent status)

## Changelog

- 2026-04-17: Initial version. Documents existing BottomStatusBar. 3 persistent status items (Engine / Safety / ZMQ) + right-aligned timestamp. FSM states displayed lowercase per codebase absolute rule.
