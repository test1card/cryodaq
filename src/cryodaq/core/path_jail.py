"""Confine user-supplied file paths to a base directory (ME-6).

The calibration import/export commands build filesystem paths straight from
an unauthenticated loopback ZMQ command dict. ``resolve_within`` is the single
guard that keeps those reads/writes inside the allowed exports directory.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_within(base: Path, user_path: str) -> Path:
    """Resolve ``user_path`` under ``base``; raise ValueError on escape.

    Each check is load-bearing:
    - reject a leading ``~`` so no home-directory expansion sneaks a path out;
    - ``os.path.realpath`` follows symlinks, so a symlink that lives inside
      ``base`` but points outside is caught by the containment check below;
    - ``os.path.commonpath`` on ``os.path.normcase``-folded strings compares
      case-insensitively where the platform is (Windows), and raises ValueError
      itself for mixed drives / UNC roots — which is exactly the escape we want.

    An absolute ``user_path`` is discarded by ``os.path.join`` and then rejected
    by the containment check; an in-base relative name resolves under ``base``.
    """
    if user_path.startswith("~"):
        raise ValueError("path outside allowed directory")

    base_real = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base_real, user_path))

    base_nc = os.path.normcase(base_real)
    full_nc = os.path.normcase(full)
    # commonpath raises ValueError across drives/UNC roots — propagates as escape.
    if os.path.commonpath([base_nc, full_nc]) != base_nc:
        raise ValueError("path outside allowed directory")

    return Path(full)
