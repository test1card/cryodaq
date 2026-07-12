from __future__ import annotations

import os
import socket
from types import SimpleNamespace

import pytest

from cryodaq.agents import assistant_bootstrap
from cryodaq.agents.assistant.soak_periodic_delivery import (
    SOAK_ARTIFACT_FD_ENV,
    SOAK_ARTIFACT_NONCE_ENV,
    SOAK_ASSISTANT_GENERATION_ENV,
)


@pytest.mark.skipif(os.name != "posix", reason="inherited AF_UNIX capability is POSIX-only")
def test_bootstrap_consumes_exact_capability_and_removes_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    parent, child = socket.socketpair()
    child.set_inheritable(True)
    monkeypatch.setenv(SOAK_ARTIFACT_FD_ENV, str(child.detach()))
    monkeypatch.setenv(SOAK_ARTIFACT_NONCE_ENV, "a" * 64)
    monkeypatch.setenv(SOAK_ASSISTANT_GENERATION_ENV, "7")
    session = assistant_bootstrap._consume_soak_periodic_session(periodic_allowed=True)
    assert session is not None
    assert session.assistant_generation == 7
    assert session._socket.get_inheritable() is False
    keys = (SOAK_ARTIFACT_FD_ENV, SOAK_ARTIFACT_NONCE_ENV, SOAK_ASSISTANT_GENERATION_ENV)
    assert all(key not in os.environ for key in keys)
    session.close_now()
    parent.close()


@pytest.mark.parametrize("missing", [SOAK_ARTIFACT_FD_ENV, SOAK_ARTIFACT_NONCE_ENV, SOAK_ASSISTANT_GENERATION_ENV])
def test_bootstrap_partial_capability_is_terminal(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    values = {
        SOAK_ARTIFACT_FD_ENV: "999999",
        SOAK_ARTIFACT_NONCE_ENV: "a" * 64,
        SOAK_ASSISTANT_GENERATION_ENV: "1",
    }
    values.pop(missing)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="partial"):
        assistant_bootstrap._consume_soak_periodic_session(periodic_allowed=True)


def test_no_capability_keeps_production_path(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (SOAK_ARTIFACT_FD_ENV, SOAK_ARTIFACT_NONCE_ENV, SOAK_ASSISTANT_GENERATION_ENV):
        monkeypatch.delenv(key, raising=False)
    assert assistant_bootstrap._consume_soak_periodic_session(periodic_allowed=True) is None


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="inherited AF_UNIX capability is POSIX-only")
async def test_bootstrap_selects_mutually_exclusive_local_factory(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent, child = socket.socketpair()
    child.set_inheritable(True)
    monkeypatch.setenv(SOAK_ARTIFACT_FD_ENV, str(child.detach()))
    monkeypatch.setenv(SOAK_ARTIFACT_NONCE_ENV, "a" * 64)
    monkeypatch.setenv(SOAK_ASSISTANT_GENERATION_ENV, "3")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    captured: dict[str, object] = {}

    class Coordinator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    class Supervisor:
        def __init__(self, **kwargs) -> None:
            captured["coordinator_factory"] = kwargs["coordinator_factory"]

        async def run(self) -> None:
            return

        async def stop(self) -> None:
            return

    def factory_builder(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        assistant_bootstrap,
        "load_report_coordinator_config",
        lambda *_a, **_k: SimpleNamespace(automatic_enabled=False),
    )
    monkeypatch.setattr(assistant_bootstrap, "ReportCoordinator", Coordinator)
    monkeypatch.setattr(assistant_bootstrap, "_strict_agent_enabled", lambda _path: False)
    monkeypatch.setattr(assistant_bootstrap, "_load_periodic_runtime", lambda: (Supervisor, factory_builder))
    with pytest.raises(RuntimeError, match="periodic PNG supervisor stopped unexpectedly"):
        await assistant_bootstrap.run(config_dir=tmp_path, data_dir=tmp_path)
    assert captured["_delivery_kind"] == "soak_local"
    assert callable(captured["_delivery_factory"])
    assert str(captured["_destination_fingerprint"]).startswith("sha256:")
    assert parent.recv(1) == b""
    parent.close()
