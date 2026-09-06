"""Compatibility re-export. The brand now lives in :mod:`cryodaq.core.branding`.

It moved on 2026-09-06 because `engine.py` needs it and MUST NOT import
anything under ``cryodaq.agents`` — `tests/test_engine_import_surface.py`
enforces that with an AST guard, and a lazy import inside a function does not
escape it. I broke that invariant in 0fdce86a by consolidating the resolver
into the assistant package and then having the engine reach for it.

The fact still has exactly one owner; only its address changed. This module
stays so the assistant and GUI import sites keep working.
"""

from __future__ import annotations

from cryodaq.core.branding import (
    DEFAULT_BRAND_EMOJI,
    DEFAULT_BRAND_NAME,
    resolve_brand_label,
    resolve_brand_name,
)

__all__ = [
    "DEFAULT_BRAND_EMOJI",
    "DEFAULT_BRAND_NAME",
    "resolve_brand_label",
    "resolve_brand_name",
]
