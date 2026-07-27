"""Shared, exact resolution of the mock-runtime environment contract."""

from __future__ import annotations

import os
from collections.abc import Mapping


def mock_env_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether ``CRYODAQ_MOCK`` explicitly requests simulated data."""

    source = os.environ if environ is None else environ
    return source.get("CRYODAQ_MOCK", "").lower() in {"1", "true"}
