"""Operator channel selection and naming, read live from Настройки.

Both the on-demand report and the whole-run overview must answer the same two
questions the same way: is this channel one the operator asked to see, and what
do they call it. Keeping the answers here means a sensor toggled or renamed in
the GUI is reflected in every report immediately, with nothing to edit twice.

Reporting must never crash on a configuration problem, so every failure here
degrades to the permissive answer (show the channel, under its raw id) rather
than propagating.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_LABELLED_CHANNELS = 64
# A name the operator never set. ChannelManager returns the placeholder for an
# unnamed channel, and "Т10 -" in a report reads like a broken label.
_PLACEHOLDER_NAMES = frozenset({"", "-", "—"})


def is_visible(channel: str) -> bool:
    """Whether this channel is enabled in Настройки."""
    try:
        from cryodaq.core.channel_manager import get_channel_manager  # noqa: PLC0415

        return bool(get_channel_manager().is_visible(channel))
    except Exception:  # pragma: no cover - reporting must never crash
        logger.debug("visibility lookup failed for %r; including it", channel, exc_info=True)
        return True


def labels_for(channels: list[str]) -> tuple[tuple[str, str], ...]:
    """Operator names for these channels; omits any without a real name."""
    try:
        from cryodaq.core.channel_manager import get_channel_manager  # noqa: PLC0415

        manager = get_channel_manager()
        pairs: list[tuple[str, str]] = []
        for channel in channels[:_MAX_LABELLED_CHANNELS]:
            # The identifier is handed to the channel authority whole. Slicing
            # a prefix off it here would be inferring what a channel is from
            # how it is spelled, which Seal C2 forbids — and an id the manager
            # does not know simply has no operator name, which is the correct
            # outcome rather than something to guess at.
            name = manager.get_name(channel)
            if name and name.strip() not in _PLACEHOLDER_NAMES:
                pairs.append((channel, manager.get_display_name(channel)))
        return tuple(pairs)
    except Exception:  # pragma: no cover - reporting must never crash
        logger.debug("label lookup failed; falling back to raw channel ids", exc_info=True)
        return ()
