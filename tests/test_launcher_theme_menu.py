"""Source-level assertions for the launcher's «Настройки → Тема» wiring.

The LauncherWindow is expensive to instantiate (spawns engine subprocess,
acquires file locks, creates tray icons), so we assert the plumbing via
text search — the same pattern used by test_launcher_backoff.py. Full
behavioral coverage happens via manual visual check after restart.
"""

from __future__ import annotations

from pathlib import Path

LAUNCHER = Path(__file__).resolve().parent.parent / "src" / "cryodaq" / "launcher.py"


def test_launcher_builds_theme_menu() -> None:
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "_build_settings_menu" in src
    assert 'addMenu("Настройки")' in src
    assert 'addMenu("Тема")' in src


def test_theme_menu_is_radio_exclusive() -> None:
    src = LAUNCHER.read_text(encoding="utf-8")
    # QActionGroup with setExclusive(True) is how Qt models radio-exclusive
    # menu items. Both tokens must be present in the settings-menu builder.
    assert "QActionGroup(self)" in src
    assert "setExclusive(True)" in src


def test_theme_menu_calls_loader_helpers() -> None:
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "from cryodaq.gui._theme_loader import" in src
    assert "available_themes" in src
    assert "_selected_theme_name" in src
    assert "write_theme_selection" in src


def test_theme_selection_prompts_confirmation() -> None:
    src = LAUNCHER.read_text(encoding="utf-8")
    # The operator must see a confirmation dialog before restart so they
    # can cancel if the app is in a dangerous state. The confirmation
    # mentions that engine is not interrupted.
    assert "QMessageBox.question" in src
    assert "Применить тему" in src
    assert "Engine и запись" in src
    assert "не прерываются" in src


def test_theme_selection_writes_before_restart() -> None:
    src = LAUNCHER.read_text(encoding="utf-8")
    # write_theme_selection must be called before _restart_gui_with_theme_change,
    # otherwise the restarted launcher would load the old theme.
    write_idx = src.index("write_theme_selection(theme_id)")
    restart_idx = src.index("self._restart_gui_with_theme_change()")
    assert write_idx < restart_idx, (
        "write_theme_selection must run before restart to persist the new "
        "selection for the re-exec'd process"
    )


def test_restart_uses_os_execv_only() -> None:
    src = LAUNCHER.read_text(encoding="utf-8")
    # The spec forbids importlib.reload cascade — only os.execv.
    assert "os.execv(sys.executable" in src
    # The docstring mentions importlib.reload to explain why we don't use
    # it; only an actual call site would be the regression. Strip comments
    # and docstrings before checking.
    import ast

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "reload":
            assert False, f"importlib.reload call found at line {node.lineno}"


def test_restart_preserves_cli_args() -> None:
    src = LAUNCHER.read_text(encoding="utf-8")
    # --mock / --tray flags must survive the re-exec.
    assert "*sys.argv[1:]" in src
