from __future__ import annotations

from pathlib import Path

import pytest

from cryodaq.core.zmq_endpoints import (
    canonical_loopback_tcp_endpoint,
    require_distinct_loopback_tcp_endpoints,
)

_ENDPOINT_OVERLAP_CASES = (
    pytest.param(
        "tcp://127.0.0.1:5556",
        "tcp://127.0.0.1:5556",
        "safe_command endpoint aliases",
        id="exact-duplicate",
    ),
    pytest.param(
        "tcp://localhost:5556",
        "tcp://127.0.0.1:5556",
        "ordinary_command endpoint must be a canonical loopback TCP address",
        id="noncanonical-localhost-alias",
    ),
)


@pytest.mark.parametrize(
    "address",
    [
        None,
        True,
        "",
        " tcp://127.0.0.1:5556",
        "tcp://127.0.0.1:5556 ",
        "TCP://127.0.0.1:5556",
        "udp://127.0.0.1:5556",
        "tcp://localhost:5556",
        "tcp://0.0.0.0:5556",
        "tcp://*:5556",
        "tcp://192.0.2.1:5556",
        "tcp://127.0.0.1:0",
        "tcp://127.0.0.1:65536",
        "tcp://127.0.0.1:05556",
        "tcp://127.0.0.01:5556",
        "tcp://user@127.0.0.1:5556",
        "tcp://127.0.0.1:5556/path",
        "tcp://127.0.0.1:5556?query",
        "tcp://127.0.0.1:5556?",
        "tcp://127.0.0.1:5556#",
        "tcp://127.0.0.1:\n5556",
        "tcp://127.0.0.1:\t5556",
        "tcp://[::1]:5556",
        "tcp://[::1%1]:5556",
        "inproc://command",
    ],
)
def test_endpoint_identity_rejects_noncanonical_nonloopback_or_non_tcp_addresses(address: object) -> None:
    with pytest.raises(ValueError, match="loopback TCP"):
        canonical_loopback_tcp_endpoint(address, label="ordinary_command")


def test_endpoint_identity_preserves_supported_independent_ipv4_addresses() -> None:
    require_distinct_loopback_tcp_endpoints(
        pub="tcp://127.0.0.1:5555",
        ordinary="tcp://127.0.0.1:5556",
        assistant="tcp://127.0.0.1:5557",
        safe="tcp://127.0.0.1:5558",
    )


def test_endpoint_identity_preserves_distinct_127_network_hosts_on_the_same_port() -> None:
    require_distinct_loopback_tcp_endpoints(
        pub="tcp://127.0.0.1:5556",
        ordinary="tcp://127.0.0.2:5556",
        assistant="tcp://127.1.2.3:5556",
        safe="tcp://127.255.255.254:5556",
    )


def test_endpoint_set_rejects_noncanonical_localhost_alias_that_raw_string_set_misses() -> None:
    ordinary = "tcp://localhost:5556"
    safe = "tcp://127.0.0.1:5556"
    assert len({ordinary, safe}) == 2

    with pytest.raises(
        ValueError,
        match="ordinary_command endpoint must be a canonical loopback TCP address",
    ):
        require_distinct_loopback_tcp_endpoints(
            ordinary_command=ordinary,
            safe_command=safe,
        )


@pytest.mark.parametrize(
    "addresses",
    [
        {"pub": "tcp://127.0.0.1:5555", "ordinary": "tcp://127.0.0.1:5555"},
        {"pub": "tcp://127.0.0.1:5555", "assistant": "tcp://127.0.0.1:5555"},
        {"pub": "tcp://127.0.0.1:5555", "safe": "tcp://127.0.0.1:5555"},
        {"ordinary": "tcp://127.0.0.1:5556", "assistant": "tcp://127.0.0.1:5556"},
        {"ordinary": "tcp://127.0.0.1:5556", "safe": "tcp://127.0.0.1:5556"},
        {"assistant": "tcp://127.0.0.1:5557", "safe": "tcp://127.0.0.1:5557"},
    ],
)
def test_endpoint_set_rejects_every_role_pair_collision(addresses: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="aliases the independent"):
        require_distinct_loopback_tcp_endpoints(**addresses)


@pytest.mark.parametrize(("ordinary_addr", "safe_addr", "error"), _ENDPOINT_OVERLAP_CASES)
def test_gui_bridge_rejects_endpoint_identity_overlap_before_allocating_any_ipc_owner(
    monkeypatch: pytest.MonkeyPatch,
    ordinary_addr: str,
    safe_addr: str,
    error: str,
) -> None:
    from cryodaq.gui import zmq_client

    def forbidden_allocation(*args, **kwargs):
        raise AssertionError("invalid endpoint configuration reached IPC allocation")

    for owner_factory in ("Queue", "JoinableQueue", "Value", "Event", "Process"):
        monkeypatch.setattr(zmq_client.mp, owner_factory, forbidden_allocation)
    monkeypatch.setattr(zmq_client, "create_safe_command_ipc", forbidden_allocation)
    with pytest.raises(ValueError, match=error):
        zmq_client.ZmqBridge(
            pub_addr="tcp://127.0.0.1:5555",
            cmd_addr=ordinary_addr,
            assistant_cmd_addr="tcp://127.0.0.1:5557",
            safe_cmd_addr=safe_addr,
        )


@pytest.mark.parametrize(("ordinary_addr", "safe_addr", "error"), _ENDPOINT_OVERLAP_CASES)
def test_subprocess_entry_revalidates_endpoint_identity_before_importing_zmq(
    monkeypatch: pytest.MonkeyPatch,
    ordinary_addr: str,
    safe_addr: str,
    error: str,
) -> None:
    from cryodaq.core import zmq_subprocess

    original_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name == "zmq":
            raise AssertionError("invalid endpoint configuration imported zmq")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded_import)
    with pytest.raises(ValueError, match=error):
        zmq_subprocess.zmq_bridge_main(
            "tcp://127.0.0.1:5555",
            ordinary_addr,
            None,
            None,
            None,
            None,
            assistant_cmd_addr="tcp://127.0.0.1:5557",
            safe_cmd_addr=safe_addr,
        )


@pytest.mark.parametrize(("ordinary_addr", "safe_addr", "error"), _ENDPOINT_OVERLAP_CASES)
def test_replay_constructor_rejects_endpoint_identity_before_source_or_socket_ownership(
    tmp_path: Path,
    ordinary_addr: str,
    safe_addr: str,
    error: str,
) -> None:
    from cryodaq.replay_engine.server import ReplayEngine

    engine = ReplayEngine.__new__(ReplayEngine)
    with pytest.raises(ValueError, match=error):
        ReplayEngine.__init__(
            engine,
            tmp_path / "never-opened.json",
            pub_addr="tcp://127.0.0.1:5555",
            cmd_addr=ordinary_addr,
            safe_cmd_addr=safe_addr,
        )
    assert vars(engine) == {}
