from __future__ import annotations

from datetime import UTC, datetime

from cryodaq.agents.assistant.shared.context_reader import ContextAuthorityCache


def test_engine_disconnect_invalidates_cached_context() -> None:
    cache = ContextAuthorityCache()
    cache.put(
        {"experiment_id": "exp-1"},
        {
            "received_at": datetime.now(UTC).isoformat(),
            "freshness_s": 60.0,
        },
    )
    assert cache.get() == {"experiment_id": "exp-1"}
    cache.invalidate()
    assert cache.get() is None
