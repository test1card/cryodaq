"""Russian plural forms for UI strings.

Phase III.D helper — replaces ad-hoc plural mistakes across the
overlays (n=1 was incorrectly rendered with the genitive-plural
suffix on severity counts). Always goes through :func:`ru_plural`;
never format a Russian count phrase with a single hardcoded suffix.
"""

from __future__ import annotations


def ru_plural(n: int, singular: str, few: str, many: str) -> str:
    """Return the correct Russian plural form for ``n``.

    Russian nominal-group agreement rules::

        1, 21, 31, 101, … → singular (nominative singular)
        2–4, 22–24, …     → few       (genitive singular)
        0, 5–20, 25–30, … → many      (genitive plural)

    Teens 11–14 are a special case — always ``many`` despite the
    last-digit rule that would predict ``singular`` / ``few``.

    Examples::

        >>> ru_plural(1, "критический", "критических", "критических")
        'критический'
        >>> ru_plural(2, "предупреждение", "предупреждения", "предупреждений")
        'предупреждения'
        >>> ru_plural(14, "канал", "канала", "каналов")
        'каналов'
        >>> ru_plural(101, "тревога", "тревоги", "тревог")
        'тревога'
    """
    n_abs = abs(int(n)) % 100
    n_last = n_abs % 10
    if 10 < n_abs < 20:
        return many
    if n_last == 1:
        return singular
    if 2 <= n_last <= 4:
        return few
    return many
