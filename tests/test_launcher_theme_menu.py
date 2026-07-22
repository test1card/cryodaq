"""Static contracts for launcher display preferences and debug logging."""

from __future__ import annotations

import ast
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parent.parent / "src" / "cryodaq" / "launcher.py"


def _launcher_source() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse(_launcher_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"launcher method not found: {name}")


def test_launcher_builds_view_theme_menu() -> None:
    src = _launcher_source()
    assert "_build_settings_menu" in src
    assert 'addMenu("\u0412\u0438\u0434")' in src
    assert 'addMenu("\u0422\u0435\u043c\u0430")' in src


def test_theme_menu_is_radio_exclusive_and_runtime_truthful() -> None:
    src = _launcher_source()
    assert "QActionGroup(self)" in src
    assert "setExclusive(True)" in src
    assert "gui_theme.ACTIVE_THEME_ID" in src
    assert "_theme_pending_action" in src
    assert "_update_theme_pending_indicator" in src


def test_theme_handler_is_only_a_deferred_selection_delegate() -> None:
    method = _method("_on_theme_selected")
    statements = method.body[1:] if isinstance(method.body[0], ast.Expr) else method.body
    assert len(statements) == 1
    assert isinstance(statements[0], ast.Return)
    call = statements[0].value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Attribute)
    assert call.func.attr == "_defer_theme_selection"


def test_launcher_contains_no_theme_reexec_implementation() -> None:
    source = _launcher_source()
    assert "_restart_gui_with_theme_change" not in source
    assert "_wait_engine_stopped" not in source
    assert "os.execv" not in source


def test_theme_deferral_has_no_process_or_acquisition_side_effect() -> None:
    method = _method("_defer_theme_selection")
    called_names: set[str] = set()
    for node in ast.walk(method):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    assert "write_theme_selection" in called_names
    assert not called_names.intersection(
        {"execv", "_stop_engine", "_stop_assistant", "_do_shutdown", "shutdown", "release_lock"}
    )


def test_launcher_debug_logging_action_exists() -> None:
    src = _launcher_source()
    assert "_debug_logging_action" in src
    assert "\\u041f\\u043e\\u0434\\u0440\\u043e\\u0431\\u043d\\u044b\\u0435" in src
    assert "checkable=True" in src
    assert "_on_debug_logging_toggled" in src


def test_launcher_debug_logging_toggle_persists_to_qsettings() -> None:
    src = _launcher_source()
    assert 'QSettings("FIAN", "CryoDAQ")' in src
    assert 'settings.setValue("logging/debug_mode"' in src


def test_launcher_propagates_debug_flag_to_engine_env() -> None:
    src = _launcher_source()
    assert "CRYODAQ_LOG_LEVEL" in src
    assert "read_debug_mode_from_qsettings" in src


def test_process_entry_points_resolve_log_level() -> None:
    src = _launcher_source()
    assert 'setup_logging("launcher", level=resolve_log_level())' in src

    gui_app = LAUNCHER.parent / "gui" / "app.py"
    assert 'setup_logging("gui", level=resolve_log_level())' in gui_app.read_text(encoding="utf-8")

    engine = LAUNCHER.parent / "engine.py"
    assert 'setup_logging("engine", level=resolve_log_level())' in engine.read_text(encoding="utf-8")
