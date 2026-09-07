"""What was said, so the next question can mean something.

Every query was a one-shot. `chat_id` reached the agent and was spent entirely
on rate limiting, so "какая температура на второй ступени?" followed by "а на
первой?" got "без контекста не угадаю, что за «первая»" — measured 2026-09-07,
and honestly answered, which is the point: it genuinely did not know.

Three rules shape this, and the first is the one that matters.

ONLY WHAT WAS SAID IS REMEMBERED. Never the state blocks — no readings, no
trends, no alarms. Those are rebuilt fresh every turn, because a remembered
temperature is a stale temperature and an assistant that quotes a three-hour-old
pressure with today's confidence is worse than one with no memory at all.

SILENCE IS PART OF THE TRANSCRIPT. A gap is marked rather than hidden, so the
model can tell a follow-up from a new morning without a rule deciding for it.

IT LIVES ON DISK. The launcher restarts this process on failure, and an
in-memory transcript would be forgotten exactly when the assistant had just
been struggling — the worst moment to lose the operator's last question.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Turns replayed into a prompt. Twenty pairs is a long conversation for one
#: stand and a small fraction of a 100k window.
DEFAULT_MAX_TURNS = 20
#: A gap longer than this is marked in the transcript. Not a boundary: an
#: overnight gap still leaves yesterday visible, because "почему ты вчера
#: писала что фит плохой?" is exactly the question worth answering.
DEFAULT_SILENCE_MARKER_S = 3 * 3600.0
#: Per-message cap. A transcript is context, not an archive.
_MAX_STORED_CHARS = 4000
#: Refuse to grow one conversation without bound; the tail is what matters.
_MAX_FILE_TURNS = 500


def _safe_chat_key(chat_id: Any) -> str:
    """A filename that cannot leave the directory it belongs in.

    `chat_id` arrives from Telegram and from any local caller, so it is treated
    as hostile input: everything outside a small alphabet is replaced, and the
    result is length-bounded.
    """
    raw = str(chat_id) if chat_id is not None else "local"
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    return (cleaned or "local")[:64]


class ConversationStore:
    """Append-only transcripts, one file per chat. Never raises."""

    def __init__(
        self,
        root: Path,
        *,
        max_turns: int = DEFAULT_MAX_TURNS,
        silence_marker_s: float = DEFAULT_SILENCE_MARKER_S,
    ) -> None:
        self._root = Path(root)
        self._max_turns = max(1, int(max_turns))
        self._silence_marker_s = float(silence_marker_s)

    def _path(self, chat_id: Any) -> Path:
        return self._root / f"{_safe_chat_key(chat_id)}.jsonl"

    def remember(self, chat_id: Any, question: str, answer: str) -> None:
        """Append one exchange. A failure here must never cost the answer."""
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            record = {
                "ts": time.time(),
                "q": (question or "").strip()[:_MAX_STORED_CHARS],
                "a": (answer or "").strip()[:_MAX_STORED_CHARS],
            }
            if not record["q"] and not record["a"]:
                return
            with self._path(chat_id).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 - memory is an enrichment
            logger.debug("conversation not stored: %s", exc)

    def _read(self, chat_id: Any) -> list[dict]:
        path = self._path(chat_id)
        try:
            if not path.is_file():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:  # noqa: BLE001
            logger.debug("conversation not read: %s", exc)
            return []
        turns: list[dict] = []
        for line in lines[-_MAX_FILE_TURNS:]:
            try:
                record = json.loads(line)
            except Exception:  # noqa: BLE001 - one bad line is not a lost history
                continue
            if isinstance(record, dict) and ("q" in record or "a" in record):
                turns.append(record)
        return turns

    def replay(self, chat_id: Any, *, now: float | None = None) -> str:
        """The recent conversation, rendered. Empty when there is none."""
        turns = self._read(chat_id)[-self._max_turns :]
        if not turns:
            return ""
        current = time.time() if now is None else now
        rows: list[str] = []
        previous_ts: float | None = None
        for record in turns:
            ts = record.get("ts")
            ts = float(ts) if isinstance(ts, int | float) else None
            if previous_ts is not None and ts is not None:
                gap = ts - previous_ts
                if gap >= self._silence_marker_s:
                    rows.append(f"[тишина {_human_gap(gap)}]")
            if ts is not None:
                previous_ts = ts
            question = str(record.get("q") or "").strip()
            answer = str(record.get("a") or "").strip()
            if question:
                rows.append(f"Оператор: {question}")
            if answer:
                rows.append(f"Ты: {answer}")
        if previous_ts is not None:
            gap = current - previous_ts
            if gap >= self._silence_marker_s:
                rows.append(f"[тишина {_human_gap(gap)} до текущего вопроса]")
        return "\n".join(rows)

    def reset(self, chat_id: Any | None = None) -> None:
        """Forget one conversation, or all of them. Used on experiment_finalize."""
        try:
            if chat_id is not None:
                self._path(chat_id).unlink(missing_ok=True)
                return
            if self._root.is_dir():
                for path in self._root.glob("*.jsonl"):
                    path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("conversation not reset: %s", exc)


def _human_gap(seconds: float) -> str:
    hours = seconds / 3600.0
    if hours < 24:
        return f"{hours:.0f} ч" if hours >= 1 else f"{seconds / 60:.0f} мин"
    return f"{hours / 24:.0f} сут"
