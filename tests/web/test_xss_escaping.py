"""Regression test for H.14: Stored XSS via operator log innerHTML."""
from pathlib import Path

SERVER_PY = Path("src/cryodaq/web/server.py")


def _dashboard_source() -> str:
    return SERVER_PY.read_text(encoding="utf-8")


def test_escape_html_helper_present():
    src = _dashboard_source()
    assert "function escapeHtml" in src


def test_operator_log_message_is_escaped():
    src = _dashboard_source()
    assert "${e.message||''}" not in src
    assert "escapeHtml(e.message" in src


def test_operator_log_author_is_escaped():
    src = _dashboard_source()
    assert "${e.author||e.source||'?'}" not in src
    assert "escapeHtml(e.author" in src


def test_channel_name_in_temp_card_is_escaped():
    src = _dashboard_source()
    assert "${ch.split(' ')[0]}" not in src
    assert "escapeHtml(ch.split" in src
