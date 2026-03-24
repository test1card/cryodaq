"""Verify Keithley panel uses debounced non-blocking updates."""
import ast
from pathlib import Path


def test_keithley_no_blocking_live_update():
    """P target and limits live-update must NOT call blocking send_command."""
    src = Path(__file__).parents[2] / "src" / "cryodaq" / "gui" / "widgets" / "keithley_panel.py"
    source = src.read_text(encoding="utf-8")
    tree = ast.parse(source)

    check_methods = {"_send_p_target", "_send_limits", "_on_p_spin_changed", "_on_limits_spin_changed"}
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in check_methods:
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        if isinstance(func, ast.Name) and func.id == "send_command":
                            violations.append(f"{node.name}:{child.lineno}")

    assert not violations, (
        "Live-update methods must not call blocking send_command:\n"
        + "\n".join(violations)
    )


def test_keithley_has_debounce_timers():
    """Keithley panel must have debounce timers for live-update."""
    src = Path(__file__).parents[2] / "src" / "cryodaq" / "gui" / "widgets" / "keithley_panel.py"
    source = src.read_text(encoding="utf-8")
    assert "_p_debounce" in source, "Missing P target debounce timer"
    assert "_limits_debounce" in source, "Missing limits debounce timer"
    assert "setSingleShot(True)" in source, "Debounce timers must be single-shot"
