"""The transport tests that bind real sockets must not pin a fixed port.

OC-039. A fixed port is a name shared with every other process on the host,
including the previous test's bridge still in TIME_WAIT or a daemon that has not
finished exiting. Two modules had independently chosen the SAME pair,
59994/59995. The bind then fails and the test times out.

It fails in the safe direction — a good candidate is rejected, a bad one is not
admitted — but a spurious red on a required partition ends a one-shot CI cycle,
and retrying until green is forbidden.

*** SCOPE, AND WHY IT IS NOT A REPO-WIDE SCAN. *** A first version of this guard
scanned every test module for a literal loopback port. It produced two classes
of false positive that no allowlist would make honest:

* ``tests/core/test_zmq_subprocess_ephemeral.py`` drives ``zmq_bridge_main`` in
  thread against a *fake* zmq module, so its ``61000``-series constants are
  handed to mocks and never reach a socket;
* ``tests/core/test_zmq_endpoint_contract.py`` names ``65536`` precisely because
  it is not a valid port — the test exists to prove it is rejected.

Text cannot tell a bind from a reference, and a guard that has to be taught
exceptions for correct code is measuring the wrong property. So this file checks
the two modules that actually bind, and says so, rather than pretending to a
coverage it does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The modules repaired for OC-039: these start real bridges on real sockets.
_REAL_SOCKET_TEST_MODULES = (
    "tests/core/test_zmq_safety.py",
    "tests/core/test_zmq_subprocess.py",
)

_FIXED_LOOPBACK_PORT = re.compile(r"tcp://127\.0\.0\.1:(\d+)")

# Only the IANA dynamic/private range is forbidden, and for a specific reason: it
# is the range the operating system draws from when it assigns an ephemeral port,
# so a literal inside it competes with the OS's own allocator. Ports below it —
# 5555, 5556, 5557 — are this product's documented service endpoints; naming one
# asserts a contract rather than binding an arbitrary port.
_DYNAMIC_RANGE_START = 49152
_DYNAMIC_RANGE_END = 65535


@pytest.mark.parametrize("module", _REAL_SOCKET_TEST_MODULES)
def test_real_socket_tests_do_not_pin_a_port_in_the_os_dynamic_range(module: str) -> None:
    offenders: list[str] = []
    text = (REPO_ROOT / module).read_text(encoding="utf-8")
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in _FIXED_LOOPBACK_PORT.finditer(line):
            port = int(match.group(1))
            if _DYNAMIC_RANGE_START <= port <= _DYNAMIC_RANGE_END:
                offenders.append(f"{module}:{line_number}: {match.group(0)}")

    assert not offenders, "port pinned inside the OS dynamic range:\n" + "\n".join(offenders)


@pytest.mark.parametrize("module", _REAL_SOCKET_TEST_MODULES)
def test_real_socket_tests_resolve_their_endpoints_dynamically(module: str) -> None:
    """Absence of a literal is not proof of a fix; the helper must be present."""

    text = (REPO_ROOT / module).read_text(encoding="utf-8")

    assert "_free_addr" in text, f"{module} no longer resolves its endpoints dynamically"


def test_the_guard_can_actually_see_the_shape_it_forbids() -> None:
    """Positive control: a regex that stopped matching would leave this green."""

    offending = _FIXED_LOOPBACK_PORT.search('addr = "tcp://127.0.0.1:59994"')
    assert offending is not None
    assert _DYNAMIC_RANGE_START <= int(offending.group(1)) <= _DYNAMIC_RANGE_END

    # An OS-assigned port carries no literal, so there is nothing to match.
    assert _FIXED_LOOPBACK_PORT.search('addr = f"tcp://127.0.0.1:{port}"') is None

    # A documented service endpoint sits below the range and stays legal.
    documented = _FIXED_LOOPBACK_PORT.search('addr = "tcp://127.0.0.1:5556"')
    assert documented is not None
    assert int(documented.group(1)) < _DYNAMIC_RANGE_START
