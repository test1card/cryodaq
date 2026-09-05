"""A partly-embedded rebuild must not report success.

`build_index` keeps row alignment by storing an unembeddable chunk as a zero
vector, logs a warning, and still swaps the staging table into place. That is a
reasonable choice on its own — the alternative is losing the whole rebuild to
one timeout — but until 2026-09-05 the CLI answered it with

    print(f"Done: {stats}")

and exit 0. A run that turned 500 of 3638 chunks into unsearchable zero vectors
was reported as a clean build, and the degraded index had already replaced the
good one.

That matters now because embeddings moved off loopback onto a relayed link that
has been observed dropping from 13 MB/s to 50 KB/s mid-transfer. Partial failure
stopped being theoretical.

The swap is deliberately NOT refused here: the index is built and whether to
keep it is the operator's decision, not the tool's. What changes is that the
outcome cannot be mistaken for a clean one.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(stats: dict) -> subprocess.CompletedProcess[str]:
    """Drive index_main with build_index stubbed to a given result."""

    program = textwrap.dedent(f"""
        import sys, asyncio
        sys.argv = ["cryodaq-rag-index", "--no-sqlite"]
        import cryodaq.agents.rag.cli as cli

        async def _fake_build_index(**kwargs):
            return {stats!r}

        cli.build_index = _fake_build_index
        cli._make_embeddings = lambda cfg: type(
            "E", (), {{"close": staticmethod(lambda: asyncio.sleep(0))}}
        )()
        cli.index_main()
    """)
    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_a_clean_rebuild_still_exits_zero() -> None:
    r = _run_cli(
        {"chunks": 10, "embedded": 10, "failed": 0, "indexed": 10, "promoted": True, "db_path": "x", "table": "t"}
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Done:" in r.stdout


def test_a_degraded_rebuild_exits_non_zero() -> None:
    r = _run_cli(
        {
            "chunks": 3638,
            "embedded": 3138,
            "failed": 500,
            "indexed": 3501,
            "promoted": False,
            "db_path": "x",
            "table": "t",
        }
    )
    assert r.returncode == 5, f"expected 5, got {r.returncode}\n{r.stdout}{r.stderr}"


def test_the_warning_names_the_scale_and_that_nothing_was_lost() -> None:
    """Rewritten 2026-09-05 after review.

    This test used to require the words "already replaced" — it pinned a
    message describing damage that had already happened. Review made the
    point that a non-zero exit then "makes the failure visible after the
    damage, not subject to an operator decision". The rebuild is now
    abandoned instead, so what the operator must learn is the scale AND that
    their working index is still there.
    """

    r = _run_cli(
        {
            "chunks": 3638,
            "embedded": 3138,
            "failed": 500,
            "indexed": 3501,
            "promoted": False,
            "db_path": "x",
            "table": "t",
        }
    )
    err = r.stderr
    assert "500/3638" in err
    assert "ABANDONED" in err
    assert "NOT replaced" in err
    assert "3501" in err, "the operator must learn what survived"
    assert "Nothing was lost" in err


def test_an_explicitly_requested_partial_promotion_says_so_instead() -> None:
    """Partial promotion stays available, and must not claim nothing was lost."""

    r = _run_cli(
        {
            "chunks": 3638,
            "embedded": 3138,
            "failed": 500,
            "indexed": 3638,
            "promoted": True,
            "db_path": "x",
            "table": "t",
        }
    )
    err = r.stderr
    assert r.returncode == 5
    assert "HAS replaced" in err
    assert "not searchable" in err.lower()
    assert "Nothing was lost" not in err


def test_one_failed_chunk_is_enough_to_flag_it() -> None:
    """No silent tolerance band — the operator decides what is acceptable."""

    r = _run_cli(
        {
            "chunks": 3638,
            "embedded": 3637,
            "failed": 1,
            "indexed": 3501,
            "promoted": False,
            "db_path": "x",
            "table": "t",
        }
    )
    assert r.returncode == 5
    assert "1/3638" in r.stderr
