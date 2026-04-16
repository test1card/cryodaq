---
title: Input Field
keywords: input, field, text, form, qlineedit, numeric, validation, focus, disabled, label
applies_to: text and numeric input widgets
status: partial
implements: ad-hoc QLineEdit usage in legacy dialogs (formalization pending)
last_updated: 2026-04-17
---

# Input Field

Single-line text or numeric input for operator data entry.

**When to use:**
- Operator-provided values in dialogs (experiment name, comment, calibration offset)
- Configuration values in Settings
- Search boxes
- Numeric setpoints (temperature target, voltage limit)

**When NOT to use:**
- Multi-line text (notes, log entries) — use `QPlainTextEdit` with similar styling
- Single-choice from list — use `QComboBox`
- Yes/no choice — use toggle or checkbox, not a text field with "да"/"нет"
- Displaying a value (not input) — use `QLabel`. Inputs are for entry, not readouts.

## Anatomy

```
Label placement: ABOVE the field (not floating, not placeholder-as-label)

┌── Имя эксперимента ──┐           ◀── label (FONT_LABEL_SIZE, MUTED_FOREGROUND)
│                      │           ◀── SPACE_1 between label and field
┌────────────────────────────────────┐
│  calibration_run_042                │   ◀── field (ROW_HEIGHT, FONT_BODY)
└────────────────────────────────────┘
 ▲
 │
 bg: SURFACE_CARD, border 1px BORDER, radius RADIUS_SM

┌────────────────────────────────────┐   ◀── SPACE_1 below (for helper/error)
│ ⚠ Имя уже занято                  │   ◀── helper/error (FONT_LABEL_SIZE, STATUS_*)
└────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Label** | Yes | `QLabel` above the field, `FONT_LABEL_SIZE`, `MUTED_FOREGROUND` color |
| **Field** | Yes | `QLineEdit`, `ROW_HEIGHT = 36`, `SURFACE_CARD` background |
| **Helper text** | No | Hint or validation message below the field, `FONT_LABEL_SIZE` |
| **Error message** | Conditional | Replaces helper text when invalid, `TEXT_FAULT` color + alert icon |
| **Unit suffix** | Numeric fields | Inline right-aligned unit label (K, мбар, Вт) per RULE-COPY-006 |

## Invariants

1. **Label ABOVE field.** Not floating, not placeholder. Placeholder-as-label fails accessibility and disappears on focus.
2. **Height = ROW_HEIGHT.** (RULE-SPACE-007)
3. **Focus ring on `:focus`.** 2px `ACCENT` border replacing 1px `BORDER`. (RULE-INTER-001)
4. **Unit always displayed for numeric fields.** Temperature field shows "K" suffix; pressure shows "мбар". (RULE-COPY-006, RULE-DATA-006)
5. **Error state distinct from disabled.** Error: `STATUS_FAULT` border (or TEXT_FAULT for message). Disabled: reduced opacity, `TEXT_DISABLED` text color. Never overlap treatments.
6. **Placeholder text is sentence case example, not instruction.** "Введите название" is a placeholder-as-label (bad). "calibration_run_042" is a placeholder example (good).
7. **No raw hex.** (RULE-COLOR-001)

## API (proposed)

```python
# src/cryodaq/gui/widgets/input_field.py  (proposed)

class InputField(QWidget):
    """Composed input: label + QLineEdit + helper/error.
    
    Signal `value_changed(str)` emits debounced text updates.
    Signal `validated(bool, str)` emits validation result on editing finished.
    """
    
    value_changed = Signal(str)
    validated = Signal(bool, str)  # (is_valid, message)
    
    def __init__(
        self,
        label: str,
        parent: QWidget | None = None,
        *,
        placeholder: str = "",
        helper: str = "",
        unit: str = "",          # "K", "мбар", "Вт", etc.
        validator: QValidator | None = None,
    ) -> None: ...
    
    def text(self) -> str: ...
    def setText(self, text: str) -> None: ...
    def set_error(self, message: str | None) -> None:
        """Show error styling with message, or clear error if None."""
    def set_enabled(self, enabled: bool) -> None: ...
```

## Variants

### Variant 1: Text input

Standard text entry.

```python
# DESIGN: RULE-SPACE-007, RULE-INTER-001, RULE-COLOR-001
label = QLabel("Имя эксперимента")
label.setFont(label_font)
label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")

field = QLineEdit()
field.setFixedHeight(theme.ROW_HEIGHT)
field.setPlaceholderText("calibration_run_042")  # example, not instruction
field.setStyleSheet(f"""
    QLineEdit {{
        background: {theme.SURFACE_CARD};
        border: 1px solid {theme.BORDER};
        border-radius: {theme.RADIUS_SM}px;
        color: {theme.FOREGROUND};
        padding: 0 {theme.SPACE_2}px;
        font-family: "{theme.FONT_BODY}";
        font-size: {theme.FONT_BODY_SIZE}px;
    }}
    QLineEdit:focus {{
        border: 2px solid {theme.ACCENT};
    }}
    QLineEdit:disabled {{
        color: {theme.TEXT_DISABLED};
        background: {theme.MUTED};
    }}
""")
```

### Variant 2: Numeric input with unit

Temperature, pressure, voltage entry with unit suffix.

```python
# DESIGN: RULE-COPY-006, RULE-DATA-006, RULE-TYPO-003
# Horizontal composition: [field] [unit label]
row = QHBoxLayout()
row.setSpacing(theme.SPACE_1)  # 4px tight gap between field and unit
row.setContentsMargins(0, 0, 0, 0)

field = QLineEdit()
field.setFixedHeight(theme.ROW_HEIGHT)
field.setValidator(QDoubleValidator(0.0, 400.0, 2))  # 0-400 K, 2 decimals
# DESIGN: RULE-TYPO-003 — tnum on numeric input
numeric_font = QFont(theme.FONT_MONO, theme.FONT_BODY_SIZE)
numeric_font.setFeature("tnum", 1)
numeric_font.setFeature("liga", 0)  # DESIGN: RULE-TYPO-004
field.setFont(numeric_font)
field.setStyleSheet(...)  # as Variant 1

unit = QLabel("K")
unit.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")

row.addWidget(field, 1)  # field expands
row.addWidget(unit, 0, Qt.AlignmentFlag.AlignVCenter)
```

### Variant 3: Search input

Text input with search icon prefix.

```python
# DESIGN: RULE-COLOR-005 (icon inherits MUTED color)
search_icon = QLabel()
search_icon.setPixmap(
    load_colored_icon("search", color=theme.MUTED_FOREGROUND)
      .pixmap(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)
)
search_icon.setFixedSize(theme.ROW_HEIGHT, theme.ROW_HEIGHT)
search_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
search_icon.setStyleSheet(f"""
    QLabel {{
        background: {theme.SURFACE_CARD};
        border: 1px solid {theme.BORDER};
        border-right: none;
        border-radius: {theme.RADIUS_SM}px 0 0 {theme.RADIUS_SM}px;
    }}
""")

field = QLineEdit()
field.setFixedHeight(theme.ROW_HEIGHT)
field.setPlaceholderText("Поиск по журналу")
field.setStyleSheet(f"""
    QLineEdit {{
        background: {theme.SURFACE_CARD};
        border: 1px solid {theme.BORDER};
        border-left: none;
        border-radius: 0 {theme.RADIUS_SM}px {theme.RADIUS_SM}px 0;
        padding: 0 {theme.SPACE_2}px;
    }}
    QLineEdit:focus {{
        border: 2px solid {theme.ACCENT};
        border-left: none;
    }}
""")

row = QHBoxLayout()
row.setSpacing(0)  # icon and field visually joined
row.setContentsMargins(0, 0, 0, 0)
row.addWidget(search_icon)
row.addWidget(field, 1)
```

### Variant 4: Password-masked input

Authentication flows.

```python
field = QLineEdit()
field.setEchoMode(QLineEdit.EchoMode.Password)
field.setFixedHeight(theme.ROW_HEIGHT)
field.setStyleSheet(...)  # as Variant 1
# Rest identical to text input
```

## States

| State | Visual treatment |
|---|---|
| **Default (empty)** | Placeholder in `MUTED_FOREGROUND`; border `BORDER` |
| **Typed content** | Text in `FOREGROUND`; border `BORDER` |
| **Hover** | Border `MUTED_FOREGROUND` (subtle) — optional, default can stay `BORDER` |
| **Focus** | Border 2px `ACCENT` (RULE-INTER-001) |
| **Valid + blurred** | Border `BORDER`; no indicator needed |
| **Invalid (error)** | Border 2px `STATUS_FAULT`; error message below in `TEXT_FAULT` with alert icon |
| **Disabled** | Background `MUTED`; color `TEXT_DISABLED`; cursor `ArrowCursor` |
| **Pending validation** | Subtle spinner in right-side region; don't block input |

## Validation patterns

### Inline validation (preferred)

Validate on `editingFinished` (blur). Show error below field. Don't validate on every keystroke — too aggressive.

```python
# DESIGN: RULE-COPY-004 — actionable error message
def _on_editing_finished(self):
    text = self._field.text().strip()
    if not text:
        self.set_error("Имя не может быть пустым.")
    elif text in self._existing_names:
        self.set_error(f"Имя '{text}' уже занято. Выберите другое.")
    elif not re.match(r'^[a-zA-Z0-9_-]+$', text):
        self.set_error("Допустимы только латинские буквы, цифры, _ и -.")
    else:
        self.set_error(None)
        self.validated.emit(True, "")
```

### Numeric bounds validation

Use `QDoubleValidator` / `QIntValidator`. Bounds enforce at input level. Out-of-range combined with soft error message:

```python
# Temperature setpoint: 0-400 K
field.setValidator(QDoubleValidator(0.0, 400.0, 2))

def _on_editing_finished(self):
    try:
        value = float(self._field.text())
    except ValueError:
        self.set_error("Введите число.")
        return
    if value < 0:
        self.set_error("Температура не может быть отрицательной.")
    elif value > 400:
        self.set_error("Максимум 400 K. Введите меньшее значение.")
    else:
        self.set_error(None)
```

### Decimal input with point-or-comma tolerance

Russian users may type comma decimal ("3,14"). Accept both, normalize to point internally.

```python
# DESIGN: RULE-COPY-008 — UI display is point decimal, but accept comma on input
def _normalize_decimal(self, text: str) -> str:
    """Accept "3,14" or "3.14", always return "3.14"."""
    return text.replace(",", ".")

def _on_editing_finished(self):
    text = self._normalize_decimal(self._field.text().strip())
    try:
        value = float(text)
    except ValueError:
        ...
```

## Reference implementation (composite InputField)

```python
# src/cryodaq/gui/widgets/input_field.py
class InputField(QWidget):
    value_changed = Signal(str)
    validated = Signal(bool, str)
    
    def __init__(
        self,
        label: str,
        parent=None,
        *,
        placeholder: str = "",
        helper: str = "",
        unit: str = "",
        validator: QValidator | None = None,
    ):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)  # DESIGN: RULE-SPACE-001
        
        # Label
        self._label = QLabel(label)
        label_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        label_font.setWeight(theme.FONT_LABEL_WEIGHT)
        self._label.setFont(label_font)
        self._label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        layout.addWidget(self._label)
        
        # Field row (with optional unit)
        self._field = QLineEdit()
        self._field.setFixedHeight(theme.ROW_HEIGHT)
        if placeholder:
            self._field.setPlaceholderText(placeholder)
        if validator is not None:
            self._field.setValidator(validator)
        self._apply_field_style()
        
        if unit:
            row = QHBoxLayout()
            row.setSpacing(theme.SPACE_1)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(self._field, 1)
            unit_label = QLabel(unit)
            unit_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
            row.addWidget(unit_label, 0, Qt.AlignmentFlag.AlignVCenter)
            row_container = QWidget()
            row_container.setLayout(row)
            layout.addWidget(row_container)
        else:
            layout.addWidget(self._field)
        
        # Helper/error
        self._helper = QLabel(helper)
        helper_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        self._helper.setFont(helper_font)
        self._helper.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        self._helper.setVisible(bool(helper))
        layout.addWidget(self._helper)
        
        # Signals
        self._field.textChanged.connect(self.value_changed)
    
    def _apply_field_style(self, error: bool = False) -> None:
        border_color = theme.STATUS_FAULT if error else theme.BORDER
        focus_color = theme.STATUS_FAULT if error else theme.ACCENT
        self._field.setStyleSheet(f"""
            QLineEdit {{
                background: {theme.SURFACE_CARD};
                border: 1px solid {border_color};
                border-radius: {theme.RADIUS_SM}px;
                color: {theme.FOREGROUND};
                padding: 0 {theme.SPACE_2}px;
                font-family: "{theme.FONT_BODY}";
                font-size: {theme.FONT_BODY_SIZE}px;
            }}
            QLineEdit:focus {{
                border: 2px solid {focus_color};
            }}
            QLineEdit:disabled {{
                color: {theme.TEXT_DISABLED};
                background: {theme.MUTED};
            }}
        """)
    
    def text(self) -> str:
        return self._field.text()
    
    def setText(self, text: str) -> None:
        self._field.setText(text)
    
    def set_error(self, message: str | None) -> None:
        if message:
            self._helper.setText(message)
            self._helper.setStyleSheet(f"color: {theme.TEXT_FAULT};")
            self._helper.setVisible(True)
            self._apply_field_style(error=True)
        else:
            self._helper.setText("")
            self._helper.setVisible(False)
            self._apply_field_style(error=False)
```

## Common mistakes

1. **Placeholder-as-label.** "Введите имя" in placeholder with no QLabel above. When user clicks, placeholder disappears and context is lost. Always use explicit label above field.

2. **Error state = disabled state.** Same greyed-out appearance for both. User can't tell if the field is broken or turned off. Use distinct treatments: error = red border + message; disabled = reduced opacity.

3. **Validating on every keystroke.** Fires error messages before user finishes typing. Wait for `editingFinished` (blur) or explicit submit.

4. **Missing unit on numeric field.** Temperature entry without "K" suffix. Ambiguous whether user enters Kelvin, Celsius, or something else. RULE-COPY-006, RULE-DATA-006.

5. **Not normalizing decimal separator.** Rejecting "3,14" because code expects "3.14". Russian users naturally type comma. Accept both. RULE-COPY-008.

6. **Vague error message.** "Ошибка." — doesn't tell operator what to do. Use actionable error per RULE-COPY-004.

7. **Missing focus ring.** Essential for keyboard navigation. RULE-INTER-001.

8. **Label in uppercase.** "ИМЯ ЭКСПЕРИМЕНТА" — use sentence case for field labels. Uppercase is for category headers per RULE-TYPO-008, not form labels.

## Related components

- `components/dialog.md` — Dialogs typically contain InputField + action buttons
- `components/button.md` — Input + button pairs (submit action)
- `patterns/numeric-formatting.md` — Rules for numeric display (inputs are entry; outputs are display — different rules)

## Changelog

- 2026-04-17: Initial version. 4 variants (text, numeric with unit, search, password). `InputField` composite class proposed. Current legacy dialogs use ad-hoc QLineEdit; formalization tracked as Phase II follow-up.
