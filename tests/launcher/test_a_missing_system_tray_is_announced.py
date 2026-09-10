"""A launcher with no way to show anything must say so.

`QSystemTrayIcon` can be constructed and shown on a desktop that provides no
system tray: Qt does not raise, the icon simply never appears. In `--tray` mode
the tray is the WHOLE interface -- no window is shown -- so a missing tray
leaves a process that is running, acquiring, and entirely invisible, with
nothing in the log to distinguish that from a launcher that never started.
`deploy/cryodaq.service` starts exactly that mode.

`TrayController` in gui/tray_status.py already returns early on this condition
and is tested for it. `LauncherWindow._build_tray` did not check at all and had
no test: two owners of the same resource, one careful, one not.

Not a refusal. Acquisition does not need a tray, and refusing to start would
trade a missing icon for missing data.

Measured on this stand 2026-09-10: the tray IS available (DISPLAY=:1). This is a
latent defect, not the cause of the autostart unit failing -- a hypothesis that
measurement refuted before this was written.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _FakeTrayIcon:
    """A QSystemTrayIcon stand-in whose availability the test controls.

    A bare `MagicMock` cannot stand in for the class: Mock's FIRST positional
    argument is `spec`, so `QSystemTrayIcon(icon, parent)` would silently
    restrict the instance to the icon object's attributes and every later call
    would raise AttributeError. The constructor here ignores its arguments on
    purpose.
    """

    available = True
    #: `closeEvent` reaches QSystemTrayIcon.MessageIcon on the happy path.
    MessageIcon = MagicMock()

    def __new__(cls, *_args, **_kwargs) -> MagicMock:
        return MagicMock()

    @staticmethod
    def isSystemTrayAvailable() -> bool:
        return _FakeTrayIcon.available


def _build_tray_on(host: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, *, available: bool) -> None:
    """Drive the real `_build_tray` against a host with no Qt behind it."""
    import cryodaq.launcher as module

    monkeypatch.setattr(_FakeTrayIcon, "available", available)
    monkeypatch.setattr(module, "QSystemTrayIcon", _FakeTrayIcon)
    monkeypatch.setattr(module, "QMenu", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr(module, "tray_icon_for_level", lambda _level: object())
    monkeypatch.setattr(module, "resolve_tray_status", lambda **_kwargs: SimpleNamespace(tooltip="", level=None))
    module.LauncherWindow._build_tray(host)


def _host(*, tray_only: bool) -> SimpleNamespace:
    return SimpleNamespace(
        _tray_only=tray_only,
        _tray=None,
        _tray_unavailable=False,
        _on_open_full_gui=MagicMock(),
        _tray_open=MagicMock(),
        _tray_minimize=MagicMock(),
        _on_restart_engine=MagicMock(),
        _on_confirm_source_disconnected=MagicMock(),
        _on_quit=MagicMock(),
        _on_tray_activated=MagicMock(),
    )


def test_a_present_tray_says_nothing(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """The guard must not fire on the normal desktop."""
    host = _host(tray_only=True)

    with caplog.at_level("WARNING", logger="cryodaq.launcher"):
        _build_tray_on(host, monkeypatch, available=True)

    assert "No system tray" not in "\n".join(record.getMessage() for record in caplog.records)


def test_losing_the_whole_interface_is_louder_than_losing_an_icon(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Level carries meaning: a lost interface is not a degraded feature.

    A reviewer pointed out that logging both at CRITICAL says the two are the
    same, when one leaves the operator with nothing and the other leaves the
    window.
    """
    with caplog.at_level("WARNING", logger="cryodaq.launcher"):
        _build_tray_on(_host(tray_only=True), monkeypatch, available=False)
        tray_only_levels = {record.levelname for record in caplog.records}
        caplog.clear()
        _build_tray_on(_host(tray_only=False), monkeypatch, available=False)
        windowed_levels = {record.levelname for record in caplog.records}

    assert tray_only_levels == {"CRITICAL"}
    assert windowed_levels == {"WARNING"}


def test_tray_mode_names_the_consequence(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """The point is not the missing tray; it is the missing interface."""
    host = _host(tray_only=True)

    with caplog.at_level("CRITICAL", logger="cryodaq.launcher"):
        _build_tray_on(host, monkeypatch, available=False)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "NO visible interface at all" in logged
    assert "acquisition continues" in logged


def test_windowed_mode_says_only_the_icon_is_lost(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The same condition is not the same consequence when a window exists."""
    host = _host(tray_only=False)

    with caplog.at_level("WARNING", logger="cryodaq.launcher"):
        _build_tray_on(host, monkeypatch, available=False)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "the tray icon will be absent" in logged
    # And the promise the message makes must be one the code keeps -- see the
    # closeEvent tests below, which is where the first version of it was false.
    assert "will not hide on close" in logged
    assert "NO visible interface at all" not in logged


def test_a_missing_tray_does_not_refuse_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refusing would trade a missing icon for missing data."""
    host = _host(tray_only=True)

    _build_tray_on(host, monkeypatch, available=False)

    assert host._tray is not None, "the tray owner must still be built; only the desktop is missing"


# ---------------------------------------------------------------------------
# The window must not hide behind a tray that cannot appear
# ---------------------------------------------------------------------------


def test_closing_does_not_hide_the_window_when_there_is_no_tray(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise "the window remains" is false, and it was.

    `closeEvent` hid the window whenever a tray OBJECT existed, and one always
    exists after construction regardless of whether the desktop can show it. So
    windowed mode on a tray-less desktop reached the same invisible-running
    process that tray mode does -- found in review, against the very message
    this change added.
    """
    import cryodaq.launcher as module

    monkeypatch.setattr(module, "QSystemTrayIcon", _FakeTrayIcon)
    monkeypatch.setattr(_FakeTrayIcon, "available", False)
    event = MagicMock()
    host = SimpleNamespace(_tray=MagicMock(), hide=MagicMock(), _shutdown_requested=False)

    module.LauncherWindow.closeEvent(host, event)

    event.ignore.assert_called_once()
    host.hide.assert_not_called()
    host._tray.showMessage.assert_not_called()


def test_closing_still_hides_the_window_when_a_tray_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """The normal desktop keeps its minimise-to-tray behaviour."""
    import cryodaq.launcher as module

    monkeypatch.setattr(module, "QSystemTrayIcon", _FakeTrayIcon)
    monkeypatch.setattr(_FakeTrayIcon, "available", True)
    tray = MagicMock()
    tray.isVisible.return_value = True
    host = SimpleNamespace(_tray=tray, hide=MagicMock(), _shutdown_requested=False)

    module.LauncherWindow.closeEvent(host, MagicMock())

    host.hide.assert_called_once()
    tray.showMessage.assert_called_once()
