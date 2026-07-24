"""Integration-test ownership for GUI command workers."""

from __future__ import annotations

import pytest

from cryodaq.gui import zmq_client


@pytest.fixture(autouse=True)
def _gui_worker_root_session() -> None:
    """Mirror the application root's explicit admission and settlement."""

    session_epoch = zmq_client.open_gui_command_worker_admission()
    try:
        yield
    finally:
        zmq_client.revoke_gui_command_worker_admission(session_epoch)
        assert zmq_client.settle_registered_gui_command_workers()
        assert zmq_client.registered_gui_command_workers() == ()
