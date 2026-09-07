"""A launcher that will not start must SAY so, not wait to be dismissed.

`deploy/cryodaq.service` has stayed disabled since 2026-09-04 for one reason:
the startup path answered a lock collision with a modal `QMessageBox.critical`
and only exited once it was dismissed. Under systemd, with nobody at the
screen, that is not an exit — it is a launcher hanging on a dialog no one can
see, and `Restart=on-failure` never fires because nothing has failed yet.

`deploy/README-autostart.md` had called that collision harmless because the
code "exits 0". True of a line the process never reaches.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.parametrize("attended", [True, False])
def test_the_refusal_is_always_logged(attended: bool, caplog: pytest.LogCaptureFixture) -> None:
    """The log is the only channel that exists unattended, and the better one attended."""
    from cryodaq.launcher import _report_startup_refusal

    with patch("cryodaq.launcher.QMessageBox") as box, caplog.at_level("ERROR"):
        _report_startup_refusal(
            attended=attended,
            title="CryoDAQ",
            message="что-то пошло не так",
            log_message="launcher lock is held by another instance",
        )

    assert "launcher lock is held by another instance" in caplog.text
    assert box.critical.called is attended


def test_unattended_startup_opens_no_dialog_at_all() -> None:
    """The defect itself: a dialog nobody can dismiss keeps the process alive."""
    from cryodaq.launcher import _report_startup_refusal

    with patch("cryodaq.launcher.QMessageBox") as box:
        _report_startup_refusal(
            attended=False,
            title="CryoDAQ",
            message="уже запущен",
            log_message="lock held",
        )

    box.critical.assert_not_called()
    box.assert_not_called()


def test_the_startup_path_routes_every_refusal_through_the_helper() -> None:
    """A bare modal added later would disable autostart again, silently.

    Source check, and deliberately so: these calls sit before the Qt event loop
    in the process's own `main`, so reaching them from a test means booting the
    launcher. The invariant that matters is that none of them is bare.
    """
    import inspect

    import cryodaq.launcher as launcher

    source = inspect.getsource(launcher.main)

    assert "QMessageBox.critical(" not in source, (
        "a refusal on the startup path opens a modal directly; unattended it will hang. "
        "Route it through _report_startup_refusal(attended=not args.tray, ...)"
    )
    assert "_report_startup_refusal(" in source
