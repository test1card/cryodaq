"""Fail-closed endpoint identity for local CryoDAQ ZMQ lanes.

The engine command surface is intentionally loopback-only. Endpoint strings
are configuration, not authority: every independent PUB, ordinary command,
assistant command, and safe command lane must resolve to a distinct canonical
loopback TCP identity before any socket, process, queue, or pipe owner is
allocated.
"""

from __future__ import annotations

import ipaddress
import re

CanonicalZmqEndpoint = tuple[int, bytes, int]
_IPV4_TCP_ENDPOINT = re.compile(
    r"tcp://(?P<host>[0-9]{1,3}(?:\.[0-9]{1,3}){3}):(?P<port>[0-9]{1,5})",
    re.ASCII,
)


def canonical_loopback_tcp_endpoint(address: object, *, label: str) -> CanonicalZmqEndpoint:
    """Return an exact IP/port identity for one local ZMQ TCP endpoint."""

    if type(address) is not str or not address or address != address.strip():
        raise ValueError(f"{label} endpoint must be a non-empty canonical loopback TCP address")
    matched = _IPV4_TCP_ENDPOINT.fullmatch(address)
    if matched is None:
        raise ValueError(f"{label} endpoint must be a canonical loopback TCP address")
    try:
        ip = ipaddress.IPv4Address(matched.group("host"))
        port = int(matched.group("port"))
    except ValueError as exc:
        raise ValueError(f"{label} endpoint must be a canonical loopback TCP address") from exc
    if not ip.is_loopback or not 1 <= port <= 65535 or address != f"tcp://{ip.compressed}:{port}":
        raise ValueError(f"{label} endpoint must be a canonical loopback TCP address")
    return (ip.version, ip.packed, port)


def require_distinct_loopback_tcp_endpoints(**addresses: object) -> None:
    """Validate local endpoint syntax and reject every canonical alias."""

    if not addresses:
        raise ValueError("at least one ZMQ endpoint is required")
    owners: dict[CanonicalZmqEndpoint, str] = {}
    for label, address in addresses.items():
        identity = canonical_loopback_tcp_endpoint(address, label=label)
        prior = owners.get(identity)
        if prior is not None:
            raise ValueError(f"{label} endpoint aliases the independent {prior} endpoint")
        owners[identity] = label
