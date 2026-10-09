"""Verify launcher exit-code handling and exponential backoff (Phase 2b H.3)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "src" / "cryodaq" / "launcher.py"


def test_launcher_imports_engine_exit_code():
    """Launcher must import ENGINE_CONFIG_ERROR_EXIT_CODE from cryodaq.engine."""
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "ENGINE_CONFIG_ERROR_EXIT_CODE" in src


def test_launcher_has_backoff_state():
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "_restart_attempts" in src
    assert "_max_restart_attempts" in src
    assert "_restart_backoff_s" in src
    assert "_restart_giving_up" in src


def test_launcher_has_modal_handlers():
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "_show_config_error_modal" in src
    assert "_show_crash_loop_modal" in src


def test_launcher_handles_engine_exit_via_helper():
    """The crash-handling logic should be in a dedicated helper, not inlined."""
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "_handle_engine_exit" in src


def test_launcher_has_restart_pending_guard():
    """Codex Phase 2b P1: _handle_engine_exit must guard against being
    called repeatedly while a restart is already scheduled (otherwise
    the 3s health timer burns the entire backoff budget in one window)."""
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "_restart_pending" in src
    # The guard must be checked at the entry of _handle_engine_exit.
    handle_idx = src.find("def _handle_engine_exit")
    assert handle_idx >= 0
    next_def = src.find("\n    def ", handle_idx + 30)
    body = src[handle_idx:next_def] if next_def >= 0 else src[handle_idx:]
    assert "if self._restart_pending" in body, (
        "_handle_engine_exit must early-return when _restart_pending is True"
    )


def test_launcher_does_not_blindly_restart():
    """The old 'restart every 3s forever' pattern must be gone — the
    restart call must be gated by giving_up / config_error checks."""
    src = LAUNCHER.read_text(encoding="utf-8")
    # The old code had `self._start_engine(wait=False)` directly inside
    # the `if not self._engine_external:` branch of _check_engine_health.
    # After Phase 2b that path goes through _handle_engine_exit which uses
    # QTimer.singleShot. Verify the immediate-restart pattern is gone.
    health_block_start = src.find("def _check_engine_health")
    assert health_block_start >= 0
    # Find the next def after _check_engine_health
    next_def = src.find("def ", health_block_start + 30)
    health_body = src[health_block_start:next_def] if next_def >= 0 else src[health_block_start:]
    # The body must NOT contain a direct unconditional _start_engine call.
    # The only restart path is now via _handle_engine_exit (QTimer.singleShot).
    assert "_start_engine(wait=False)" not in health_body, (
        "_check_engine_health still contains direct _start_engine call — "
        "should delegate to _handle_engine_exit"
    )
