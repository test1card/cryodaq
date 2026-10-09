"""Verify Thyracont validate_checksum default (Phase 2c Codex F.2)."""

from __future__ import annotations

from cryodaq.drivers.instruments.thyracont_vsp63d import ThyracontVSP63D


def test_validate_checksum_default_on():
    """Default MUST be True after Phase 2c (was False in earlier releases)."""
    t = ThyracontVSP63D(name="vacuum", resource_str="COM3")
    assert t._validate_checksum is True, (
        "Thyracont checksum validation must default to True. "
        "Operators with known-bad firmware can opt out via instruments.local.yaml."
    )


def test_validate_checksum_can_be_disabled():
    """Explicit opt-out still works for legacy firmware."""
    t = ThyracontVSP63D(name="vacuum", resource_str="COM3", validate_checksum=False)
    assert t._validate_checksum is False
