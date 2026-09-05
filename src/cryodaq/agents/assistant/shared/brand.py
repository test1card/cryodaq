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
