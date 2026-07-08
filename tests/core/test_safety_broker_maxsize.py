"""SafetyBroker.subscribe must reject a non-positive maxsize (A2).

``asyncio.Queue(maxsize=0)`` is unbounded — its ``full()`` never returns
True, which silently disables the overflow→FAULT contract the safety
channel exists to enforce. Fail-closed: reject rather than run without it.
Because ``max_safety_backlog`` from safety.yaml flows straight into this
argument, this guard also validates that config value at its use point.
"""

from __future__ import annotations

import pytest

from cryodaq.core.safety_broker import SafetyBroker


@pytest.mark.parametrize("bad_maxsize", [0, -1, -100])
def test_subscribe_rejects_nonpositive_maxsize(bad_maxsize: int) -> None:
    broker = SafetyBroker()
    with pytest.raises(ValueError, match="maxsize must be > 0"):
        broker.subscribe("safety_manager", maxsize=bad_maxsize)
    # Rejection must not half-register the subscriber.
    assert broker.stats["subscribers"] == 0


def test_subscribe_accepts_positive_maxsize_and_overflow_still_fires() -> None:
    broker = SafetyBroker()
    q = broker.subscribe("safety_manager", maxsize=1)
    assert q.maxsize == 1
    # A bounded queue reports full() → the overflow contract is intact.
    q.put_nowait(object())
    assert q.full() is True
