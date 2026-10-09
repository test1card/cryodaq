"""A thinking-first model must not leak its scratchpad to the operator.

LFM2.5 emits the reasoning trace ahead of the answer and closes it with
``</think>``; the opening tag is consumed as a control token and never
reaches the HTTP response. A paired-tag strip therefore leaves the whole
monologue in place, and the operator reads it in Telegram before the two
sentences they asked for.
"""

from cryodaq.agents.assistant.shared.ollama_client import strip_reasoning


def test_unpaired_close_drops_everything_before_it():
    raw = "The user asks a greeting.\nRules say be brief.</think>Привет! Я РМКПшка."
    assert strip_reasoning(raw) == "Привет! Я РМКПшка."


def test_paired_block_is_removed():
    assert strip_reasoning("<think>scratch</think>Ответ") == "Ответ"


def test_text_between_paired_blocks_is_kept():
    # Both blocks are unambiguously delimited, so everything outside them is
    # answer text — not reasoning to be discarded.
    assert strip_reasoning("<think>a</think>первая <think>b</think>вторая") == "первая вторая"


def test_plain_answer_is_untouched():
    assert strip_reasoning("Просто ответ без тегов") == "Просто ответ без тегов"


def test_unterminated_block_returns_raw_text():
    # The answer never arrived (truncated generation). Showing the raw text
    # beats handing the operator an empty bubble.
    raw = "<think>reasoning that never closed"
    assert strip_reasoning(raw) == raw


def test_reasoning_only_output_returns_raw_text():
    raw = "всё это размышление</think>   "
    assert strip_reasoning(raw) == "всё это размышление</think>"


def test_empty_stays_empty():
    assert strip_reasoning("") == ""
