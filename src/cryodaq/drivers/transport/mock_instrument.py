"""Mock-only client for an external instrument simulator process."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MockInstrumentEndpoint:
    """One loopback TCP endpoint owned by an external test process."""

    host: str
    port: int

    def __post_init__(self) -> None:
        """Reject direct construction that would bypass parser safety checks."""

        if self.host != "127.0.0.1":
            raise ValueError("mock instrument endpoint must use the literal address 127.0.0.1")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("mock instrument endpoint port must be an integer in 1..65535")

    @classmethod
    def parse(cls, value: str) -> MockInstrumentEndpoint:
        """Parse HOST:PORT without accepting remote hosts."""

        if not isinstance(value, str) or value.count(":") != 1:
            raise ValueError("mock instrument endpoint must use HOST:PORT")
        host, port_text = (part.strip() for part in value.split(":", 1))
        if host != "127.0.0.1":
            raise ValueError("mock instrument endpoint must use the literal address 127.0.0.1")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError("mock instrument endpoint port must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("mock instrument endpoint port must be in 1..65535")
        return cls(host=host, port=port)


class ExternalMockInstrumentClient:
    """Exchange one line per connection with the external mock instrument."""

    def __init__(self, endpoint: MockInstrumentEndpoint, *, timeout_s: float = 2.0) -> None:
        if isinstance(timeout_s, bool) or not math.isfinite(float(timeout_s)) or float(timeout_s) <= 0.0:
            raise ValueError("timeout_s must be a finite positive number")
        self.endpoint = endpoint
        self._timeout_s = float(timeout_s)

    async def query(self, command: str, timeout_ms: int | None = None) -> str:
        """Send one ASCII command and return one newline-terminated reply.

        ``timeout_ms`` overrides the client default per call, mirroring the
        transport ``query(..., timeout_ms=...)`` contract so external and
        in-process paths keep the same configured timing.
        """

        if not isinstance(command, str) or not command.strip() or "\n" in command or "\r" in command:
            raise ValueError("mock instrument command must be one non-empty line")
        if timeout_ms is not None:
            if isinstance(timeout_ms, bool) or not math.isfinite(float(timeout_ms)) or float(timeout_ms) <= 0:
                raise ValueError("timeout_ms must be a finite positive number")

        async def _exchange() -> str:
            reader, writer = await asyncio.open_connection(self.endpoint.host, self.endpoint.port)
            try:
                writer.write(command.strip().encode("ascii") + b"\n")
                await writer.drain()
                raw = await reader.readline()
            finally:
                writer.close()
                await writer.wait_closed()
            if not raw.endswith(b"\n"):
                raise RuntimeError("external mock instrument returned no complete line")
            try:
                response = raw.decode("ascii").strip()
            except UnicodeDecodeError as exc:
                raise RuntimeError("external mock instrument returned non-ASCII data") from exc
            if response.startswith("ERROR "):
                raise RuntimeError(response[6:] or "external mock instrument rejected the command")
            return response

        timeout_s = float(timeout_ms) / 1000.0 if timeout_ms is not None else self._timeout_s
        return await asyncio.wait_for(_exchange(), timeout=timeout_s)

    async def set_power(self, power_w: float) -> None:
        """Tell the external plant which mock heater power CryoDAQ requested."""

        if isinstance(power_w, bool) or not math.isfinite(float(power_w)) or float(power_w) < 0.0:
            raise ValueError("power_w must be a finite non-negative number")
        response = await self.query(f"MOCK:POWER {float(power_w):.17g}")
        if response != "OK":
            raise RuntimeError(f"external mock instrument did not accept power: {response!r}")
