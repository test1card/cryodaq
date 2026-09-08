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

import hashlib
import json
import logging
import os
import re
import threading
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
#: Total cap on a replayed transcript. Twenty pairs at the per-message cap
#: allow 160000 characters, which on dense Cyrillic can crowd out the answer
#: inside a 100000-token window — the memory would then cost exactly the reply
#: it exists to improve. Reviewed 2026-09-07. Oldest turns are dropped first.
_MAX_REPLAY_CHARS = 24000
#: Refuse to grow one conversation without bound; the tail is what matters.
#: Enforced ON WRITE by rotation, not merely on read: reviewed 2026-09-07, the
#: file grew forever and every replay read all of it before slicing, so an
#: old conversation cost more I/O each turn and would eventually fill the DAQ
#: disk. Rotation keeps the file small enough that reading it is cheap.
_MAX_FILE_TURNS = 500
#: Rotate when the file exceeds the cap by this much, so a rewrite happens once
#: per _ROTATE_SLACK turns rather than on every append.
_ROTATE_SLACK = 100
#: How many experiments' transcripts to keep per chat. Rotation bounds each
#: file; this bounds their number, which per-experiment keying made unbounded.
_MAX_SCOPES_PER_CHAT = 12
#: Refuse to read a transcript larger than this. Rotation keeps files small, so
#: reaching it means corruption, and corruption must not stall the event loop.
_MAX_FILE_BYTES = 4 * 1024 * 1024
#: How long one writer waits for another. Short: the work behind it is a few
#: kilobytes, so anything longer means the disk is not answering.
_LOCK_WAIT_S = 5.0


def _safe_key(raw: str, fallback: str) -> str:
    """A filename that cannot leave its directory and cannot collide.

    These ids arrive from Telegram and from the experiment state file, so they
    are treated as hostile input: everything outside a small alphabet becomes
    `_` and the result is length-bounded.

    That sanitising is lossy, and losing it silently is the danger: `run 1` and
    `run?1` both become `run_1`, and two ids sharing their first 64 characters
    become the same file. Either way one run reads another run's transcript and
    the agent answers with numbers from a stand that was never involved. So a
    digest of the ORIGINAL string is appended — short, because it only has to
    separate ids, not authenticate them.
    """
    text = (raw or "").strip()
    if not text:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", text)[:48] or fallback
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{cleaned}-{digest}"


def _safe_chat_key(chat_id: Any) -> str:
    return _safe_key(str(chat_id) if chat_id is not None else "", "local")


def _safe_scope_key(scope: Any) -> str:
    return _safe_key(str(scope) if scope is not None else "", "no-experiment")


class ConversationStore:
    """Append-only transcripts, one file per chat per experiment. Never raises.

    ONE EXPERIMENT, ONE CONTEXT. The boundary of a conversation is not a day and
    not a timeout — it is the experiment being run. Questions asked during a
    cooldown are about that cooldown; carrying them into the next run gives the
    agent a transcript whose numbers describe a stand that no longer exists,
    and stale context reads exactly like confident error. Starting the next
    experiment starts a new transcript, and the previous one stays on disk.

    A gap in TIME is not a boundary and is deliberately not treated as one: an
    overnight silence inside one experiment leaves yesterday visible, because
    "почему ты вчера писала что фит плохой?" is a question worth answering.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_turns: int = DEFAULT_MAX_TURNS,
        silence_marker_s: float = DEFAULT_SILENCE_MARKER_S,
        scope_provider: Any | None = None,
    ) -> None:
        self._root = Path(root)
        self._max_turns = max(1, int(max_turns))
        self._silence_marker_s = float(silence_marker_s)
        self._scope_provider = scope_provider
        # Appends and rotation now run in worker threads, and rotation is a
        # read-modify-write: without this, request A can read the file, request
        # B can append its exchange, and A can then replace the file with its
        # own earlier snapshot — B's answer silently gone. The temp file used
        # for the rewrite was shared too.
        self._lock = threading.Lock()

    def _scope(self) -> str:
        """The active experiment, or a stable stand-in.

        A provider that fails must not cost the memory: an unreadable experiment
        id falls back to one fixed bucket rather than to a new file each turn,
        which would silently amnesiac the assistant one question at a time.
        """
        if self._scope_provider is None:
            return "no-experiment"
        try:
            return _safe_scope_key(self._scope_provider())
        except Exception as exc:  # noqa: BLE001 - memory is an enrichment
            logger.debug("conversation scope unavailable: %s", exc)
            return "no-experiment"

    def _legacy_path(self, chat_id: Any) -> Path:
        """Where this chat's transcript lived before any of this existed.

        ONE shape, deliberately. Per-experiment scoping and the digest were
        added the same night and neither was ever deployed, so the only file
        that can exist on a real disk is the original `<chat>.jsonl`. The
        intermediate `<chat>__<scope>.jsonl` was also read for a while, and
        review pointed out the obvious: recovering it means stripping the digest
        back to the ambiguous form, which is precisely the collision the digest
        was added to prevent — `run 1` and `run?1` would read each other's
        conversation. A path that never existed is not worth a collision.

        The chat id alone cannot collide across experiments, because it does not
        name one.
        """
        raw = str(chat_id) if chat_id is not None else ""
        plain = re.sub(r"[^A-Za-z0-9_-]", "_", raw.strip())[:64] or "local"
        return self._root / f"{plain}.jsonl"

    def _path(self, chat_id: Any, scope: str | None = None) -> Path:
        """The transcript file. `scope` pins one experiment for a whole query.

        Without pinning, the provider is consulted afresh for every call — the
        classifier's replay, the format prompt's replay and the final remember —
        so an experiment transition during a long question could classify from
        one run's transcript, format from another's, and file the exchange under
        a third. One question is one conversation.
        """
        resolved = self._scope() if scope is None else scope
        return self._root / f"{_safe_chat_key(chat_id)}__{resolved}.jsonl"

    def current_scope(self) -> str:
        """Resolve the experiment once, to be passed back for the whole query."""
        return self._scope()

    def _prune_scopes(self, chat_id: Any, *, keep: Path | None = None) -> None:
        """Keep only the most recent transcripts for one chat.

        Per-file rotation bounds each file; it does not bound how MANY there
        are, and a new one appears for every experiment. On a stand that runs
        experiments continuously that grows without limit on the same disk the
        DAQ writes to.

        `keep` is the transcript just written, and it is excluded EXPLICITLY.
        The first version relied on it being newest by modification time, and
        said so in a comment that was stronger than the code: a clock
        correction, a restored file, or a late answer pinned to an older scope
        could all leave the live transcript ranked below twelve others and
        unlinked.
        """
        try:
            prefix = f"{_safe_chat_key(chat_id)}__"
            files = sorted(
                self._root.glob(f"{prefix}*.jsonl"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if keep is not None:
                files = [item for item in files if item != keep]
                limit = max(_MAX_SCOPES_PER_CHAT - 1, 0)
            else:
                limit = _MAX_SCOPES_PER_CHAT
            for stale in files[limit:]:
                stale.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - housekeeping never costs an answer
            logger.debug("conversation scopes not pruned: %s", exc)

    def remember(self, chat_id: Any, question: str, answer: str, *, scope: str | None = None) -> None:
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
            path = self._path(chat_id, scope)
            # BOUNDED WAIT FOR A BUSY PEER. An unbounded acquire piles every
            # later append behind whoever holds the lock, in worker threads
            # their async wrappers have already abandoned. Memory is an
            # enrichment: losing one exchange beats collecting threads.
            #
            # It does NOT bound the filesystem. A call that stalls while holding
            # the lock holds it forever and the `finally` never runs, and the
            # `mkdir` above happens before the lock at all. Bounding that needs
            # an interruptible write, which the filesystem does not offer. Said
            # here because the previous wording claimed the accumulation was
            # prevented, and it is only made less likely.
            if not self._lock.acquire(timeout=_LOCK_WAIT_S):
                logger.debug("conversation not stored: writer busy")
                return
            try:
                # CARRY THE OLD FILE OVER. Reading the legacy name rescued the
                # first replay after an upgrade and nothing after it: the first
                # `remember` created the new file, and every later replay found
                # it and stopped looking. If the move cannot happen, drop THIS
                # exchange instead of stranding the history behind a new file.
                if not self._migrate_legacy(chat_id, path):
                    return
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._rotate_if_needed(path)
                self._prune_scopes(chat_id, keep=path)
            finally:
                self._lock.release()
        except Exception as exc:  # noqa: BLE001 - memory is an enrichment
            logger.debug("conversation not stored: %s", exc)

    def _migrate_legacy(self, chat_id: Any, path: Path) -> bool:
        """Move a pre-upgrade transcript under the current name. Once, really.

        RENAMED, not copied. Copying left the old file in place, so the same
        pre-upgrade conversation was pulled into experiment A, then again into B
        when B first wrote, and into every run after — the opposite of one
        experiment, one context, and with the oldest run's numbers along for the
        ride. A rename consumes it: after the first migration there is nothing
        left to migrate.

        Returns False only when a migration was needed and did not happen. The
        caller then skips this exchange rather than creating the new file
        without the history, which would strand it for good: the fallback read
        only looks at the legacy name while the current one is absent.
        """
        try:
            if path.exists():
                return True
            legacy = self._legacy_path(chat_id)
            if not legacy.is_file() or legacy == path:
                return True
            legacy.rename(path)
            self._trim_partial_tail(path)
            return True
        except Exception as exc:  # noqa: BLE001 - memory is an enrichment
            logger.debug("conversation not migrated: %s", exc)
            return False

    @staticmethod
    def _trim_partial_tail(path: Path) -> None:
        """Drop an unterminated last line and guarantee a trailing newline.

        A transcript is JSONL and is appended to, so a process killed mid-write
        leaves a partial record with no newline. Migrating that file and then
        appending the next exchange fuses the two into one invalid line, and
        both are lost on replay. Worse, if the partial write stopped inside a
        multi-byte character, decoding the whole file raises and every exchange
        in it — old and new — becomes unreadable for good.

        Bytes, not text, precisely because the tail may not decode.
        """
        try:
            raw = path.read_bytes()
        except OSError:
            return
        if not raw or raw.endswith(b"\n"):
            return
        cut = raw.rfind(b"\n")
        path.write_bytes(raw[: cut + 1] if cut >= 0 else b"")

    def _rotate_if_needed(self, path: Path) -> None:
        """Keep only the recent tail on disk. Never raises."""
        try:
            with path.open("r", encoding="utf-8") as handle:
                lines = handle.readlines()
            if len(lines) <= _MAX_FILE_TURNS + _ROTATE_SLACK:
                return
            tail = lines[-_MAX_FILE_TURNS:]
            # Per FILE, not one shared name: two rotations at once would
            # otherwise write the same temporary and one would replace the
            # other's target with the other's content.
            temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
            temporary.write_text("".join(tail), encoding="utf-8")
            temporary.replace(path)
        except Exception as exc:  # noqa: BLE001 - rotation is housekeeping
            logger.debug("conversation not rotated: %s", exc)

    def _read(self, chat_id: Any, scope: str | None = None) -> list[dict]:
        path = self._path(chat_id, scope)
        try:
            if not path.is_file():
                legacy = self._legacy_path(chat_id)
                if not legacy.is_file():
                    return []
                path = legacy
            # Size first. This runs on the query handler's event loop, so a
            # corrupt or absurdly large file must cost the memory, not the
            # answer: an unbounded read there stalls every deadline above it.
            if path.stat().st_size > _MAX_FILE_BYTES:
                logger.debug("conversation ignored: %s is %d bytes", path.name, path.stat().st_size)
                return []
            # `errors="replace"`: a byte left half-written by a killed process
            # must cost the line it is in, not every exchange in the file. The
            # damaged line then fails its own json.loads and is skipped below.
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
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

    def replay(self, chat_id: Any, *, now: float | None = None, scope: str | None = None) -> str:
        """The recent conversation, rendered. Empty when there is none."""
        turns = self._read(chat_id, scope)[-self._max_turns :]
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
        # Drop from the FRONT: the recent exchange is what "а на первой?" needs,
        # and an old turn is the cheapest thing to lose.
        dropped = 0
        while rows and sum(len(row) + 1 for row in rows) > _MAX_REPLAY_CHARS:
            rows.pop(0)
            dropped += 1
        if dropped:
            rows.insert(0, f"[…{dropped} более ранних реплик опущено]")
        return "\n".join(rows)

    def reset(self, chat_id: Any | None = None) -> None:
        """Forget one conversation, or all of them. Used on experiment_finalize."""
        try:
            if chat_id is not None:
                # Every experiment's transcript for this chat, not just the
                # active one: "забудь" means forget, not "forget this run".
                prefix = f"{_safe_chat_key(chat_id)}__"
                for path in self._root.glob(f"{prefix}*.jsonl"):
                    path.unlink(missing_ok=True)
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
