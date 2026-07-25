"""Integration-test ownership for GUI command workers."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from cryodaq.gui import zmq_client


@pytest.fixture(autouse=True)
def _gui_worker_root_session() -> Iterator[int]:
    """Mirror the application root's explicit admission and settlement.

    Yields the session epoch. In production the composition root both opens the
    session and stores the epoch on itself (``LauncherWindow.__init__`` ->
    ``self._gui_worker_session_epoch``), so ``_quiesce_for_shutdown`` can revoke
    exactly that session. A test driving shutdown against a synthetic host must
    therefore give that host this epoch, otherwise ``_quiesce_for_shutdown``
    silently skips the revoke and ``settle_registered_gui_command_workers()``
    can never return True.
    """

    session_epoch = zmq_client.open_gui_command_worker_admission()
    try:
        yield session_epoch
    finally:
        zmq_client.revoke_gui_command_worker_admission(session_epoch)
        assert zmq_client.settle_registered_gui_command_workers()
        assert zmq_client.registered_gui_command_workers() == ()
