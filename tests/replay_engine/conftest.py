"""conftest for tests/replay_engine — golden-file regen flag (roadmap D4).

``--update-golden`` lets a developer intentionally refresh the checked-in
golden JSON after a deliberate analytics/alarm behavior change:

    pytest tests/replay_engine/test_golden_replay.py --update-golden
    pytest tests/replay_engine/test_golden_replay.py  # verify against the refreshed golden
"""

from __future__ import annotations

import errno
import socket
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
import zmq

_REPLAY_PORT_ATTEMPTS = 5


@dataclass(frozen=True)
class ReplayTcpEndpoints:
    pub_addr: str
    cmd_addr: str
    safe_cmd_addr: str

    @property
    def addresses(self) -> tuple[str, str, str]:
        return self.pub_addr, self.cmd_addr, self.safe_cmd_addr


@contextmanager
def _reserved_replay_tcp_endpoints() -> Iterator[ReplayTcpEndpoints]:
    """Reserve three distinct OS-assigned ports until the engine is built."""

    listeners = tuple(socket.socket(socket.AF_INET, socket.SOCK_STREAM) for _ in range(3))
    try:
        for listener in listeners:
            listener.bind(("127.0.0.1", 0))
        addresses = tuple(f"tcp://127.0.0.1:{listener.getsockname()[1]}" for listener in listeners)
        yield ReplayTcpEndpoints(*addresses)
    finally:
        for listener in listeners:
            listener.close()


def _retryable_generated_port_collision(
    error: RuntimeError,
    endpoints: ReplayTcpEndpoints,
) -> bool:
    """Recognize only a settled startup failure on one generated endpoint."""

    if type(error) is not RuntimeError or str(error) != "replay startup failed":
        return False

    cause = error.__context__
    if type(cause) is RuntimeError:
        messages = tuple(
            f"[spec Q1] Port {address.rsplit(':', 1)[1]} ({address}) is already in use — "
            "another engine is likely running. Stop the real engine first, or pass "
            "--force-replay to override."
            for address in endpoints.addresses
        )
        return str(cause) in messages

    if not isinstance(cause, zmq.ZMQError) or cause.errno not in {
        errno.EADDRINUSE,
        zmq.EADDRINUSE,
    }:
        return False

    traceback = cause.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_name == "_bind_with_retry":
            return True
        traceback = traceback.tb_next
    return False


async def _start_replay_engine(
    factory: Callable[[ReplayTcpEndpoints], Any],
) -> tuple[Any, ReplayTcpEndpoints]:
    """Start on OS-selected ports, retrying only their post-reservation race."""

    for _attempt in range(_REPLAY_PORT_ATTEMPTS):
        with _reserved_replay_tcp_endpoints() as endpoints:
            engine = factory(endpoints)
        try:
            await engine.start()
        except RuntimeError as error:
            if not _retryable_generated_port_collision(error, endpoints):
                raise
        else:
            return engine, endpoints

    pytest.fail(f"OS-selected replay ports collided {_REPLAY_PORT_ATTEMPTS} times")


@pytest.fixture
def start_replay_engine() -> Callable[
    [Callable[[ReplayTcpEndpoints], Any]],
    Awaitable[tuple[Any, ReplayTcpEndpoints]],
]:
    return _start_replay_engine


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate golden JSON fixtures under tests/replay_engine/golden/ "
        "instead of asserting the harness output against them.",
    )


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-golden"))
