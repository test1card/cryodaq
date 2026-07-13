from __future__ import annotations

import os
import socket
import subprocess
import sys

import pytest

from scripts import soak_mock_stack_runner as runner


def test_runner_launcher_endpoint_crosses_only_explicit_pass_fds() -> None:
    if os.name != "posix":
        with pytest.raises(runner._RunnerActivationDisabled, match="artifact capability is POSIX-only"):
            runner._ArtifactCapabilityPair.create()
        return

    capability = runner._ArtifactCapabilityPair.create()
    fd = capability.launcher.fileno()
    code = "import os,sys; fd=int(sys.argv[1]); print(os.fstat(fd).st_mode)"
    child = subprocess.run(
        [sys.executable, "-c", code, str(fd)],
        pass_fds=capability.child_pass_fds(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert child.stdout.strip()
    assert capability.child_environment()[runner._ARTIFACT_NONCE_ENV] == capability.nonce
    capability.close()


def test_runner_capability_has_no_network_or_path_selection() -> None:
    if os.name != "posix":
        with pytest.raises(runner._RunnerActivationDisabled, match="artifact capability is POSIX-only"):
            runner._ArtifactCapabilityPair.create()
        return

    capability = runner._ArtifactCapabilityPair.create()
    try:
        assert capability.runner.family == socket.AF_UNIX
        assert capability.launcher.family == socket.AF_UNIX
        assert not any(hasattr(capability, name) for name in ("bind", "listen", "accept", "connect", "path", "url"))
    finally:
        capability.close()


def test_runner_terminal_activation_remains_fused() -> None:
    with pytest.raises(runner._RunnerActivationDisabled):
        runner._PosixSoakRunner().run()
