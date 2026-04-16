---
title: Toast
keywords: toast, notification, snackbar, ephemeral, auto-dismiss, stack, corner, transient
applies_to: non-blocking transient notifications
status: proposed
implements: not yet — currently log messages and inline banners substitute
last_updated: 2026-04-17
---

# Toast

Transient, non-blocking notification that appears in a viewport corner, announces an event, and auto-dismisses after a short duration. For information that deserves visual attention but doesn't require operator action.

**When to use:**
- Success confirmation after an operator action («Параметры сохранены»)
- Non-critical info that the system wants to surface («Запись в архив начата»)
- Warnings that operator should notice but don't block work («Калибровка Т5 устареет через 3 дня»)
- Confirmation that an async operation completed («Экспорт HDF5 готов»)

**When NOT to use:**
- Blocking questions requiring answer — use `Dialog`
- Critical faults requiring acknowledgement — use `Dialog` with icon + fault status; fault alerts should NOT auto-dismiss
- Inline validation — use `InputField` error state
- Detailed info requiring reading — use `Popover` or `Modal`
- Persistent status that stays visible — that's a banner or badge, not a toast

## Fault alerts are NOT toasts

A critical fault is too important to auto-dismiss. Per RULE-INTER-006, faults must appear instantly and remain visible until operator acknowledges. Use:
- `Dialog` (variant 3 "Alert") for blocking acknowledgement, OR
- Persistent banner in a fixed page region for faults

Toasts are for **informational** events that could fade away without harming operator situational awareness.

## Anatomy

```
                                                  ┌──────────────────────────┐
                                                  │ ◀── toast card            │
                                                  │     bg: SURFACE_ELEVATED   │
                                                  │     radius: RADIUS_MD      │
                                                  │     border 1px BORDER      │
                                                  │     padding: CARD_PADDING  │
                                                  │     width: ~320-400         │
                                                  │                            │
                                                  │  ┌────┐ Title            × │
                                                  │  │icon│ Body 1-2 lines    │
                                                  │  └────┘                    │
                                                  │                            │
                                                  │  [optional action link]    │
                                                  │                            │
                                                  └──────────────────────────┘
                                                    ◀── 3-5s auto-dismiss
                                                        (unless hovered)

┌──────────────────────────────────────────────────────────────────────────┐
│ Viewport                                                                 │
│                                                                          │
│  Main content                                                            │
│                                                                          │
│                                             ┌──────────────────────────┐ │
│                                             │ Newer toast (stack top)  │ │
│                                             └──────────────────────────┘ │
│                                             ┌──────────────────────────┐ │
│                                             │ Older toast              │ │
│                                             └──────────────────────────┘ │
│                                             ◀── corner: top-right default │
│                                             ◀── SPACE_2 gap between       │
│ [Bottom status bar — don't overlap]                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Toast card** | Yes | QFrame with surface, border, radius, shadow (elevation exception) |
| **Status icon** | Conditional | For warning/info/caution — per RULE-A11Y-002 pair color with icon |
| **Title** | Yes | Short 1-line summary, FONT_LABEL_SIZE semibold |
| **Body** | Optional | 1-2 lines of detail, FONT_LABEL_SIZE regular, MUTED_FOREGROUND |
| **Close button** | Yes | Small × in top-right, icon-only 24×24 |
| **Action link** | Optional | Secondary action — e.g., "Открыть файл" for export-ready toast |
| **Progress indicator** | Conditional | Thin bar at bottom showing time until auto-dismiss |

## Invariants

1. **Non-blocking.** Toast never blocks operator interaction with main UI.
2. **Corner-positioned, stacked.** Fixed corner (typically top-right). Multiple toasts stack with `SPACE_2` gap.
3. **Auto-dismiss by default.** 3s for success/info, 5s for warnings. Hover pauses timer; leave resumes.
4. **Click-to-dismiss.** Close button or click anywhere on toast (except action link) dismisses immediately.
5. **Status never color alone.** Include icon for warning/caution/info contexts. (RULE-A11Y-002)
6. **Never for critical faults.** Faults use Dialog or persistent banner. Toast auto-dismiss is wrong signal for critical alerts.
7. **Max stack size.** 3-4 visible toasts. Older ones dismiss automatically when new ones arrive if stack full.
8. **Not below status bar.** Respect `BOTTOM_BAR_HEIGHT` when positioning bottom-corner toasts.
9. **Single accent per toast.** One status color dominates — info blue, success green, warning amber. (RULE-COLOR-003)
10. **Actionable text.** Body describes what happened AND optionally what operator can do. (RULE-COPY-004)

## API (proposed)

```python
# src/cryodaq/gui/widgets/toast.py  (proposed)

class Toast(QWidget):
    """Transient notification."""
    
    LEVEL_SUCCESS = "success"
    LEVEL_INFO = "info"
    LEVEL_WARNING = "warning"
    # LEVEL_FAULT deliberately absent — faults use Dialog
    
    DURATION_SHORT = 3000   # ms for success/info
    DURATION_LONG = 5000    # ms for warnings
    
    dismissed = Signal()
    action_clicked = Signal()
    
    def __init__(
        self,
        parent: QWidget,
        title: str,
        body: str = "",
        *,
        level: str = LEVEL_INFO,
        duration_ms: int | None = None,  # None = auto based on level
        action_label: str | None = None,
    ) -> None: ...
    
    def show_in(self, container: "ToastContainer") -> None:
        """Show toast inside the container (which handles stacking)."""


class ToastContainer(QWidget):
    """Corner-anchored container that manages toast stacking."""
    
    POSITION_TOP_RIGHT = "top-right"
    POSITION_BOTTOM_RIGHT = "bottom-right"
    POSITION_TOP_LEFT = "top-left"
    POSITION_BOTTOM_LEFT = "bottom-left"
    
    MAX_VISIBLE = 4
    
    def __init__(
        self,
        parent: QWidget,
        *,
        position: str = POSITION_TOP_RIGHT,
        offset: QPoint = QPoint(24, 24),
    ) -> None: ...
    
    def push(self, toast: Toast) -> None:
        """Add toast to stack. Older toasts dismiss if over MAX_VISIBLE."""
```

## Variants

### Variant 1: Success

Confirms operator action succeeded.

```python
# DESIGN: RULE-COPY-004 (concrete), RULE-INTER-007 (related success echo rule)
toast = Toast(
    parent=main_window,
    title="Параметры сохранены",
    body="Калибровочные коэффициенты Т11 обновлены.",
    level=Toast.LEVEL_SUCCESS,
    duration_ms=Toast.DURATION_SHORT,  # 3s
)
toast_container.push(toast)
```

### Variant 2: Info

Neutral informational event.

```python
toast = Toast(
    parent=main_window,
    title="Запись в архив начата",
    body="Данные эксперимента сохраняются в SQLite.",
    level=Toast.LEVEL_INFO,
    duration_ms=Toast.DURATION_SHORT,
)
toast_container.push(toast)
```

### Variant 3: Info with action

Informational event with optional action the operator may click.

```python
toast = Toast(
    parent=main_window,
    title="Экспорт HDF5 готов",
    body="",
    level=Toast.LEVEL_SUCCESS,
    duration_ms=5000,  # longer — gives operator time to click action
    action_label="Показать в папке",
)
toast.action_clicked.connect(lambda: subprocess.Popen(["explorer", export_dir]))
toast_container.push(toast)
```

### Variant 4: Warning

Non-blocking attention-worthy info.

```python
toast = Toast(
    parent=main_window,
    title="Калибровка устаревает",
    body="Датчик Т5 калиброван 97 дней назад. Рекомендуется повторить.",
    level=Toast.LEVEL_WARNING,
    duration_ms=Toast.DURATION_LONG,  # 5s — warning deserves longer visibility
    action_label="Открыть калибровку",
)
toast.action_clicked.connect(self._open_calibration_screen)
toast_container.push(toast)
```

## Reference card style

```python
# DESIGN: RULE-SURF-001, RULE-SURF-003, RULE-COLOR-008, RULE-A11Y-002
def _apply_card_style(self) -> None:
    level_colors = {
        "success": theme.STATUS_OK,
        "info":    theme.STATUS_INFO,
        "warning": theme.STATUS_WARNING,
    }
    accent_color = level_colors.get(self._level, theme.STATUS_INFO)
    
    self._frame.setStyleSheet(f"""
        #toastFrame {{
            background: {theme.SURFACE_ELEVATED};
            border: 1px solid {theme.BORDER};
            border-left: 3px solid {accent_color};  /* left accent stripe */
            border-radius: {theme.RADIUS_MD}px;
        }}
    """)
```

Left-edge 3px accent stripe provides status signal in addition to icon — two redundant channels per RULE-A11Y-002.

## Icon by level

```python
level_icons = {
    "success": "check-circle",
    "info":    "info",
    "warning": "alert-triangle",
}
icon_name = level_icons[self._level]
icon = QLabel()
icon.setPixmap(
    load_colored_icon(icon_name, color=accent_color)
      .pixmap(theme.ICON_SIZE_MD, theme.ICON_SIZE_MD)
)
```

## Auto-dismiss timer with hover pause

```python
class Toast(QWidget):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        body: str = "",
        *,
        level: str = "info",
        duration_ms: int | None = None,
        action_label: str | None = None,
        # Additional parameters omitted for brevity.
    ):
        super().__init__(parent)
        self._total_duration = duration_ms or self.DURATION_SHORT
        self._remaining = self._total_duration
        
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        
        self._start_time = 0.0
        
        # ... build UI
    
    def show_in(self, container: "ToastContainer") -> None:
        self.show()
        self._start_time = time.monotonic()
        self._timer.start(self._remaining)
    
    def enterEvent(self, event) -> None:
        """Pause timer while hovered."""
        if self._timer.isActive():
            elapsed = int((time.monotonic() - self._start_time) * 1000)
            self._remaining = max(0, self._remaining - elapsed)
            self._timer.stop()
        super().enterEvent(event)
    
    def leaveEvent(self, event) -> None:
        """Resume timer on leave."""
        if self._remaining > 0:
            self._start_time = time.monotonic()
            self._timer.start(self._remaining)
        super().leaveEvent(event)
    
    def _dismiss(self) -> None:
        # DESIGN: RULE-INTER-005 — exit faster than enter
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(150)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self._finalize)
        anim.start()
    
    def _finalize(self) -> None:
        self.dismissed.emit()
        self.hide()
        self.deleteLater()
```

## Stack management

```python
class ToastContainer(QWidget):
    def push(self, toast: Toast) -> None:
        # If at max, dismiss oldest
        if len(self._active_toasts) >= self.MAX_VISIBLE:
            oldest = self._active_toasts[0]
            oldest._dismiss()  # will remove itself via signal
        
        toast.setParent(self)
        toast.dismissed.connect(lambda t=toast: self._remove(t))
        self._active_toasts.append(toast)
        
        self._relayout()
        toast.show_in(self)
    
    def _remove(self, toast: Toast) -> None:
        if toast in self._active_toasts:
            self._active_toasts.remove(toast)
        self._relayout()
    
    def _relayout(self) -> None:
        """Stack toasts vertically with SPACE_2 gap, newest on top."""
        if self._position == self.POSITION_TOP_RIGHT:
            y = self._offset.y()
            x = self.parent().width() - self._offset.x()
            # Stack downward
            for toast in self._active_toasts:
                toast_w = toast.sizeHint().width()
                toast_h = toast.sizeHint().height()
                toast.setGeometry(x - toast_w, y, toast_w, toast_h)
                y += toast_h + theme.SPACE_2
        elif self._position == self.POSITION_BOTTOM_RIGHT:
            # Must account for BOTTOM_BAR_HEIGHT if status bar present
            y = self.parent().height() - self._offset.y() - theme.BOTTOM_BAR_HEIGHT
            # Stack upward
            for toast in reversed(self._active_toasts):
                toast_w = toast.sizeHint().width()
                toast_h = toast.sizeHint().height()
                toast.setGeometry(
                    self.parent().width() - self._offset.x() - toast_w,
                    y - toast_h,
                    toast_w, toast_h
                )
                y -= (toast_h + theme.SPACE_2)
```

## States

| State | Visual treatment |
|---|---|
| **Entering** | Slide in from edge + fade in, ~250ms |
| **Visible** | Fully opaque, timer running |
| **Hovered** | Timer paused (no visual change to card) |
| **Dismissing** | Fade out ~150ms, then remove from layout |

Progress bar (optional): thin 2px line at bottom of toast, fills from 100% to 0% as timer counts down. Provides operator a sense of remaining time.

## Common mistakes

1. **Toast for critical fault.** Auto-dismiss wrong signal — operator may miss the fault. Use Dialog. RULE-INTER-006.

2. **Too long body.** Toast with paragraph of text exceeds 5s read time. Keep to 1-2 lines. If more context needed, add "Подробнее" action link opening Modal.

3. **Toast stack explosion.** System emits 10 toasts in quick succession during a sequence of events. Throttle: batch similar toasts, or use a single "aggregate" toast ("5 записей сохранены" instead of 5 separate toasts).

4. **No hover pause.** Operator tries to read, toast dismisses mid-read. Hover must pause timer.

5. **Below status bar.** Bottom-right toast overlaps BOTTOM_BAR_HEIGHT (28px) region. Offset by bar height.

6. **Color-only status.** Success toast that's just green with no icon — fails RULE-A11Y-002. Include check icon + "Сохранено" text.

7. **Position shift on dismiss.** When middle toast of a stack dismisses, others should animate to new positions (not jump). Use QPropertyAnimation on geometry.

8. **Dismiss interrupts click.** Operator clicks action link, but toast dismisses before click registers. Click on action must be prioritized and dismiss after action emit.

9. **Two close affordances conflict.** Close × + click-anywhere-to-dismiss — click on body text dismisses but user expected only × to dismiss. Either click-anywhere dismisses (and × is redundant shortcut) OR only × dismisses (and click on body does nothing). Pick one.

## Related components

- `components/dialog.md` — Blocking acknowledgement for faults
- `components/popover.md` — For contextual richer info
- `cryodaq-primitives/bottom-status-bar.md` — Persistent status; toast complements but doesn't replace
- `patterns/state-visualization.md` — When to use toast vs banner vs badge

## Changelog

- 2026-04-17: Initial version. 4 variants (success, info, info+action, warning). `Toast` and `ToastContainer` classes proposed — not yet implemented. Faults deliberately excluded; use Dialog. Stack management, hover pause, animation asymmetry documented.
