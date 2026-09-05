"""The assistant's operator-facing identity, in exactly one place.

The operator renamed the assistant to РМКПшка. It then kept introducing itself
as Гемма, and the rename was "finished" three times before this file existed:

    2026-09-05  three literals in telegram_commands.py and launcher.py
    2026-09-05  a fourth in live/agent.py, found by reading a boot log
    2026-09-05  five more in the GUI panels and the DOCX report, found by review

Every round fixed the sites someone thought to look at, and every round left
the operator being greeted by the retired name somewhere else. The defect was
never the individual literals — it was that the name had no single home, so
"all of them" could not be checked, only guessed at.

Latin ``gemma`` is deliberately NOT covered by this. ``gemma4:e4b`` is a model
identifier, ``gemma.*`` is a retained legacy config namespace, and
``data/agents/gemma/audit`` is a legacy path kept for migration. Those are
identifiers that happen to share a word with a retired display name, and
renaming them would break compatibility for no operator-visible gain.
"""

from __future__ import annotations

#: What the operator sees the assistant call itself.
DEFAULT_BRAND_NAME = "РМКПшка"

#: Prefixed to the name on surfaces that carry one.
DEFAULT_BRAND_EMOJI = "🤖"


def resolve_brand_name(*, fallback: str = DEFAULT_BRAND_NAME) -> str:
    """The operator's configured assistant name, or ``fallback``.

    Reads ``config/agent.yaml`` the way the assistant itself does, so a rename
    there reaches every surface rather than only the ones wired to
    AssistantConfig. Review of 2026-09-05 noted the gap this closes: the
    default was centralised, but the GUI widgets used the CONSTANT while
    Telegram used the configured value, so a rename in agent.yaml would move
    one and not the other.

    yaml is imported lazily and every failure falls back, because this is
    called from GUI start-up and from failure paths, and a missing or broken
    config must never be the reason an operator loses a window or a warning.
    """
    try:
        import yaml

        from cryodaq.paths import get_config_dir

        raw = yaml.safe_load((get_config_dir() / "agent.yaml").read_text(encoding="utf-8")) or {}
        name = str((raw.get("agent") or {}).get("brand_name", "")).strip()
        return name or fallback
    except Exception:  # pragma: no cover - never break a caller for a config read
        return fallback


def resolve_brand_label(*, fallback: str = "Ассистент", with_emoji: bool = True) -> str:
    """``emoji + name`` for prefixes and notifications.

    The fallback is deliberately NEUTRAL rather than a brand: a message sent
    when the config could not be read should not assert a name that may be
    wrong. That is why callers on failure paths pass no brand at all.
    """
    try:
        import yaml

        from cryodaq.paths import get_config_dir

        raw = yaml.safe_load((get_config_dir() / "agent.yaml").read_text(encoding="utf-8")) or {}
        section = raw.get("agent") or {}
        name = str(section.get("brand_name", "")).strip()
        if not name:
            return fallback
        if not with_emoji:
            return name
        emoji = str(section.get("brand_emoji", DEFAULT_BRAND_EMOJI)).strip()
        return f"{emoji} {name}".strip()
    except Exception:  # pragma: no cover
        return fallback
