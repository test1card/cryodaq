"""The one rule that turns a runtime reading into a stable channel ID.

Instruments emit readings labelled with the string from ``instruments.yaml``,
which is the stable ID with a human name appended::

    instruments.local.yaml:  1: Т1 Криостат верх
    Reading.channel       →  "Т1 Криостат верх"
    stable channel ID     →  "Т1"

The ID is what ``channels.yaml`` keys on, what the daily database stores, and
what an operator writes in a configuration file. The trailing words are a name,
and names get edited — on 2026-09-02 every sensor on this stand was renamed.

Two consequences that this module exists to stop repeating:

* ``ChannelStateTracker`` already derived the ID with an inline
  ``reading.channel.split(" ", 1)[0]``. ``VacuumGuard`` therefore resolves ``Т12``
  correctly, because it reads through the tracker.
* ``ThermalCalculator`` receives the RAW readings and compared
  ``Reading.channel`` against a configured bare ID, so it matched nothing —
  silently, once per tick, for as long as it was misconfigured.

Anything that has to line a configured channel reference up against a live
reading asks this function, so the two cannot diverge again.

This is deliberately NOT a fuzzy lookup. It does not consult display names and
it will not find a channel by its human label; ``ChannelManager.find_by_name``
exists for that and using it here would put the physics back at the mercy of
editable text. This is a pure syntactic projection of a runtime label onto the
identity that precedes it.
"""

from __future__ import annotations

from typing import Final

_SEPARATOR: Final = " "


def channel_id_of(runtime_label: str) -> str:
    """Return the stable channel ID carried by a runtime reading label.

    ``"Т1 Криостат верх"`` → ``"Т1"``. A label with no name appended is already
    an ID and is returned unchanged, which is what instrument-path channels such
    as ``"Keithley_1/smua/power"`` and ``"VSP63D_1/pressure"`` rely on.
    """

    label = runtime_label.strip()
    head, separator, _ = label.partition(_SEPARATOR)
    return head if separator else label


def matches_channel_id(runtime_label: str, channel_id: str) -> bool:
    """Whether a runtime reading belongs to the given stable channel ID.

    Exact comparison after projection — never a prefix or substring test, so
    ``"Т1"`` does not match ``"Т12 Теплообменник 2"``.
    """

    return channel_id_of(runtime_label) == channel_id.strip()
