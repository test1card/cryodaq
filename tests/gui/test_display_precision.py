"""Guards for the display-precision helper."""

from __future__ import annotations


def test_failed_sync_does_not_leave_the_new_value_live(tmp_path, monkeypatch) -> None:
    """A write that never reached disk must not change what the next reader sees.

    Codex, P2 at 8e02047d95: `setValue()` mutates Qt's SHARED IN-PROCESS CACHE
    before `sync()` runs.  When sync failed - a read-only settings directory, a
    full disk - `set_precision_mode` returned False while the new value was
    already live.  The launcher unchecks the menu item and tells the operator
    nothing changed, and the next periodic render switches precision anyway.

    The operator is then looking at a display whose precision does not match what
    the application told him it is, which is the quiet half of "make sure he knows
    what is up".
    """

    from PySide6.QtCore import QSettings

    from cryodaq.gui.display_precision import (
        PRECISION_MODE_SETTINGS_KEY,
        precision_mode_enabled,
        set_precision_mode,
    )

    store = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    store.setValue(PRECISION_MODE_SETTINGS_KEY, False)
    store.sync()
    assert precision_mode_enabled(store) is False

    real_status = store.status

    def _access_error():
        return QSettings.Status.AccessError

    monkeypatch.setattr(store, "status", _access_error, raising=False)
    accepted = set_precision_mode(True, store)
    monkeypatch.setattr(store, "status", real_status, raising=False)

    assert accepted is False, "a failed sync must be reported as a failure"
    assert precision_mode_enabled(store) is False, "the failed write left the new value live in the settings cache"
