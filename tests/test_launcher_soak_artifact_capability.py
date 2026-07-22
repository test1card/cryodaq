from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from cryodaq import launcher


@pytest.mark.skipif(os.name != "posix", reason="pass_fds is POSIX-only")
def test_launcher_consumes_and_duplicates_only_exact_artifact_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "isolated"
    root.mkdir(mode=0o700)
    runner, inherited = socket.socketpair()
    inherited.set_inheritable(True)
    inherited_fd = inherited.detach()
    monkeypatch.setenv("CRYODAQ_ROOT", str(root))
    monkeypatch.setenv(launcher._SOAK_ARTIFACT_FD_ENV, str(inherited_fd))
    monkeypatch.setenv(launcher._SOAK_ARTIFACT_NONCE_ENV, "b" * 64)
    capability = launcher._consume_soak_artifact_capability(
        bridge_handshake=object(),  # type: ignore[arg-type]
        cli_mock=True,
        tray_only=True,
        replay_requested=False,
        setup_wizard=False,
    )
    assert capability is not None
    duplicate, generation, environment = capability.child_grant()
    try:
        assert generation == 1
        assert environment[launcher._SOAK_ASSISTANT_GENERATION_ENV] == "1"
        assert os.get_inheritable(duplicate) is False
        capability.commit_generation(generation)
        assert capability.generation == 1
    finally:
        os.close(duplicate)
        capability.close()
        runner.close()


def test_launcher_strips_every_soak_descriptor_key() -> None:
    environment = {
        launcher._SOAK_BRIDGE_FD_ENV: "3",
        launcher._SOAK_BRIDGE_NONCE_ENV: "a" * 64,
        launcher._SOAK_ARTIFACT_FD_ENV: "4",
        launcher._SOAK_ARTIFACT_NONCE_ENV: "b" * 64,
        launcher._SOAK_ASSISTANT_GENERATION_ENV: "1",
        "KEEP": "yes",
    }
    assert launcher._without_soak_bridge_environment(environment) == {"KEEP": "yes"}


@pytest.mark.skipif(os.name != "posix", reason="pass_fds is POSIX-only")
def test_failed_child_grant_may_reuse_candidate_but_committed_replacement_is_newer() -> None:
    runner, retained = socket.socketpair()
    capability = launcher._SoakArtifactCapability(retained.detach(), "b" * 64)
    first_fd, first_generation, _ = capability.child_grant()
    os.close(first_fd)
    retry_fd, retry_generation, _ = capability.child_grant()
    assert retry_generation == first_generation == 1
    capability.commit_generation(retry_generation)
    os.close(retry_fd)
    replacement_fd, replacement_generation, _ = capability.child_grant()
    assert replacement_generation == 2
    os.close(replacement_fd)
    capability.close()
    runner.close()


@pytest.mark.skipif(os.name != "posix", reason="pass_fds is POSIX-only")
def test_real_exec_receives_only_intended_duplicate() -> None:
    runner, retained = socket.socketpair()
    capability = launcher._SoakArtifactCapability(retained.detach(), "b" * 64)
    duplicate, generation, grant = capability.child_grant()
    environment = launcher._without_soak_bridge_environment(os.environ)
    environment.update(grant)
    code = (
        "import os,socket; "
        "fd=int(os.environ['CRYODAQ_SOAK_ARTIFACT_FD']); "
        "s=socket.socket(fileno=fd); "
        "assert s.family==socket.AF_UNIX; "
        "assert os.environ['CRYODAQ_SOAK_ASSISTANT_GENERATION']=='1'; "
        "print('ok')"
    )
    try:
        child = subprocess.run(
            [sys.executable, "-c", code],
            env=environment,
            pass_fds=(duplicate,),
            capture_output=True,
            text=True,
            check=True,
        )
        assert child.stdout.strip() == "ok"
        capability.commit_generation(generation)
        os.fstat(capability.fd)
    finally:
        os.close(duplicate)
        capability.close()
        runner.close()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="real fork unavailable")
def test_at_fork_guard_closes_retained_original_in_generic_child() -> None:
    runner, retained = socket.socketpair()
    launcher._guard_soak_bridge_fd_from_descendants(retained.fileno())
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            os.fstat(retained.fileno())
        except OSError:
            os.write(write_fd, b"closed")
        else:
            os.write(write_fd, b"open")
        os._exit(0)
    os.close(write_fd)
    assert os.read(read_fd, 16) == b"closed"
    os.waitpid(pid, 0)
    launcher._SOAK_BRIDGE_ACTIVE_FDS.discard(retained.fileno())
    retained.close()
    runner.close()
    os.close(read_fd)


def test_artifact_close_retains_same_descriptor_after_close_failure(monkeypatch) -> None:
    read_fd, write_fd = os.pipe()
    launcher._guard_soak_bridge_fd_from_descendants(write_fd)
    owner = launcher._SoakArtifactCapability(write_fd, "f" * 64)
    real_close = launcher.os.close

    def fail_owned(fd: int) -> None:
        if fd == write_fd:
            raise OSError("injected close failure")
        real_close(fd)

    monkeypatch.setattr(launcher.os, "close", fail_owned)
    with pytest.raises(RuntimeError, match="remained open"):
        owner.close()
    assert owner._closed is False
    assert write_fd in launcher._SOAK_BRIDGE_ACTIVE_FDS

    monkeypatch.setattr(launcher.os, "close", real_close)
    owner.close()
    assert owner._closed is True
    assert write_fd not in launcher._SOAK_BRIDGE_ACTIVE_FDS
    os.close(read_fd)
