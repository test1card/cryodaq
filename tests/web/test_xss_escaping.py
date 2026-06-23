"""Regression test for H.14: Stored XSS via operator log innerHTML.

DEFERRED (needs JS/browser harness — 2026-06-23):
  The escapeHtml function is defined in CLIENT-SIDE JavaScript embedded in
  the HTML template string in server.py.  The FastAPI endpoints /api/status
  and /api/log return raw JSON; the browser JS calls escapeHtml() before
  setting innerHTML.  There is no server-side Python HTML escaping to exercise
  with httpx/pytest.  Driving the real escaping path requires a headless
  browser (Playwright/Selenium).  Until that harness exists, the four
  behavioural tests below are replaced by structural source-grep guards that
  confirm:
    1. the escapeHtml helper is present in the served JS,
    2. all raw-interpolation anti-patterns are absent,
    3. every innerHTML-bound variable passes through escapeHtml.
  These guards catch regressions (accidental removal / bypass) without a
  browser, but they do not execute the JS.  Track as DEFERRED-XSS-01.
"""

from pathlib import Path

SERVER_PY = Path("src/cryodaq/web/server.py")


def _dashboard_source() -> str:
    return SERVER_PY.read_text(encoding="utf-8")


# --- structural guards (source-grep) ---


def test_escape_html_helper_present():
    """escapeHtml JS helper must exist in the served HTML."""
    src = _dashboard_source()
    assert "function escapeHtml" in src


def test_operator_log_message_is_escaped():
    """Raw ${e.message} interpolation must be absent; escapeHtml wrapper must be present."""
    src = _dashboard_source()
    assert "${e.message||''}" not in src, "raw message interpolation found — XSS risk"
    assert "escapeHtml(e.message" in src, "escapeHtml wrapper for message not found"


def test_operator_log_author_is_escaped():
    """Raw ${e.author} interpolation must be absent; escapeHtml wrapper must be present."""
    src = _dashboard_source()
    assert "${e.author||e.source||'?'}" not in src, "raw author interpolation found — XSS risk"
    assert "escapeHtml(e.author" in src, "escapeHtml wrapper for author not found"


def test_channel_name_in_temp_card_is_escaped():
    """Raw ${ch.split...} interpolation must be absent; escapeHtml wrapper must be present."""
    src = _dashboard_source()
    assert "${ch.split(' ')[0]}" not in src, "raw channel name interpolation found — XSS risk"
    assert "escapeHtml(ch.split" in src, "escapeHtml wrapper for channel name not found"
