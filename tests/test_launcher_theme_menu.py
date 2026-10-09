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
    # can cancel if the app is in a dangerous state. The dialog now warns
    # that engine is also restarted (IV.1 finding 1 — the prior "engine
    # keeps running" claim was incorrect, orphaned engine deadlocked REP).
    assert "QMessageBox.question" in src
    assert "Применить тему" in src
    assert "Engine и интерфейс будут перезапущены" in src
    assert "возобновятся автоматически" in src


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


# ----------------------------------------------------------------------
# IV.4 F2 — debug-logging toggle + engine env-var propagation
# ----------------------------------------------------------------------


def test_launcher_debug_logging_action_exists() -> None:
    """Settings menu hosts a «Подробные логи» checkable QAction.

    The label is encoded as \\uXXXX escapes in source to keep the
    ASCII-only convention used elsewhere in launcher.py, so the
    grep looks for the escape sequence for «Подробные» (Cyrillic П
    U+041F + о U+043E + д U+0434 + р U+0440 + о U+043E + б U+0431
    + н U+043D + ы U+044B + е U+0435) followed by a space and the
    unicode escape for «логи».
    """
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "_debug_logging_action" in src
    # "Подробные логи" is stored as unicode escapes in source — match
    # the generated action-label string literally.
    assert "\\u041f\\u043e\\u0434\\u0440\\u043e\\u0431\\u043d\\u044b\\u0435" in src, (
        "launcher must declare «Подробные» label for the debug-logging action"
    )
    assert "checkable=True" in src
    assert "_on_debug_logging_toggled" in src


def test_launcher_debug_logging_toggle_persists_to_qsettings() -> None:
    """The toggle writes logging/debug_mode into QSettings."""
    src = LAUNCHER.read_text(encoding="utf-8")
    assert 'QSettings("FIAN", "CryoDAQ")' in src
    assert 'settings.setValue("logging/debug_mode"' in src


def test_launcher_debug_logging_toggle_informs_about_restart() -> None:
    """Dialog text explicitly mentions that restart is needed."""
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "перезапуска" in src or "перезапуск" in src.lower()


def test_launcher_propagates_debug_flag_to_engine_env() -> None:
    """_start_engine sets CRYODAQ_LOG_LEVEL=DEBUG in the spawned
    engine subprocess's env when QSettings says debug mode is on."""
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "CRYODAQ_LOG_LEVEL" in src
    assert "read_debug_mode_from_qsettings" in src


def test_launcher_uses_resolve_log_level_on_startup() -> None:
    """The launcher's main() picks up the flag via resolve_log_level."""
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "resolve_log_level" in src
    assert 'setup_logging("launcher", level=resolve_log_level())' in src


def test_gui_app_uses_resolve_log_level_on_startup() -> None:
    """cryodaq-gui entry point also respects the resolve_log_level contract."""
    gui_app = Path(__file__).resolve().parent.parent / "src" / "cryodaq" / "gui" / "app.py"
    src = gui_app.read_text(encoding="utf-8")
    assert "resolve_log_level" in src
    assert 'setup_logging("gui", level=resolve_log_level())' in src


def test_engine_uses_resolve_log_level_on_startup() -> None:
    """cryodaq-engine entry point also respects the resolve_log_level contract."""
    engine = Path(__file__).resolve().parent.parent / "src" / "cryodaq" / "engine.py"
    src = engine.read_text(encoding="utf-8")
    assert "resolve_log_level" in src
    assert 'setup_logging("engine", level=resolve_log_level())' in src
