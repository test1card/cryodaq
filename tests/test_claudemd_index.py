"""Regression gates for the repository's canonical developer guidance."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / "AGENTS.md"
CLAUDE = REPO_ROOT / "CLAUDE.md"
ORCHESTRATION = REPO_ROOT / "docs" / "ORCHESTRATION.md"


def test_canonical_guidance_files_exist_and_cross_link() -> None:
    assert AGENTS.is_file()
    assert CLAUDE.is_file()
    assert ORCHESTRATION.is_file()

    agents_text = AGENTS.read_text(encoding="utf-8")
    claude_text = CLAUDE.read_text(encoding="utf-8")
    orchestration_text = ORCHESTRATION.read_text(encoding="utf-8")

    assert "docs/ORCHESTRATION.md" in agents_text
    assert "AGENTS.md" in claude_text
    assert "docs/ORCHESTRATION.md" in claude_text
    assert "../AGENTS.md" in orchestration_text


def test_claude_file_is_a_thin_pointer_not_a_second_policy() -> None:
    text = CLAUDE.read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) < 1_024
    assert "canonical repository" in text
    assert "Индекс модулей" not in text
    assert "src/cryodaq/" not in text


def test_canonical_guidance_is_stable_not_campaign_state() -> None:
    text = (
        AGENTS.read_text(encoding="utf-8")
        + CLAUDE.read_text(encoding="utf-8")
        + ORCHESTRATION.read_text(encoding="utf-8")
    )
    assert "<claude-mem-context>" not in text
    assert "# Memory Context\n" not in text
    assert "get_observations([IDs])" not in text
    assert not re.search(
        r"\b(?:commit|sha|head|master)\b[^0-9a-f\n]{0,16}`?[0-9a-f]{7,40}\b",
        text,
        flags=re.IGNORECASE,
    ), "commit SHA leaked into permanent guidance"
    assert not re.search(r"`[0-9a-f]{7,40}`", text, flags=re.IGNORECASE), (
        "bare backticked commit SHA leaked into permanent guidance"
    )
    assert "feat/montana" not in text
    assert not re.search(
        r"\b(?:Fable|Opus|Sonnet|GLM(?:-[0-9.]+)?|Grok|Luna|Terra|GPT-[0-9.]+|"
        r"Gemini|Codex|Qwen|DeepSeek)\b",
        text,
        flags=re.IGNORECASE,
    ), "transient model/provider routing leaked into permanent guidance"


def test_product_agent_and_developer_agent_are_explicitly_separated() -> None:
    agents_text = AGENTS.read_text(encoding="utf-8")
    orchestration_text = ORCHESTRATION.read_text(encoding="utf-8")
    assert "govern the shipped\noperator assistant, not developer agents" in agents_text
    assert "## 8. Product assistant boundary" in orchestration_text
    assert "exact allowlisted read-only engine queries" in agents_text
    assert "may not send mutating/control commands" in orchestration_text
    assert "Periodic PNG reporting is a separate observational" in orchestration_text


def test_gitignore_does_not_hide_canonical_guidance() -> None:
    for path in (AGENTS, CLAUDE, ORCHESTRATION):
        relative = path.relative_to(REPO_ROOT).as_posix()
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", relative],
            cwd=REPO_ROOT,
            check=False,
            timeout=10,
        )
        assert result.returncode == 1, f"canonical guidance is ignored: {relative}"


def test_machine_generated_memory_target_is_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", ".claude/claude-mem-context.md"],
        cwd=REPO_ROOT,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0


def test_canonical_guidance_is_tracked() -> None:
    for path in (AGENTS, CLAUDE, ORCHESTRATION):
        relative = path.relative_to(REPO_ROOT).as_posix()
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == 0, f"canonical guidance is not tracked: {relative}"


def test_safety_and_design_system_floors_remain_present() -> None:
    agents_text = AGENTS.read_text(encoding="utf-8")
    required = (
        "## Mission and safety boundary",
        "Software simulation, mocks, and loopback tests do not satisfy a physical",
        "verified-OFF",
        "## GUI, UX, and design-system gate",
        "Every GUI/UI/UX change is also a design-system change assessment",
        "## Stop conditions",
        ".claude/claude-mem-context.md",
    )
    missing = [phrase for phrase in required if phrase not in agents_text]
    assert not missing, f"canonical safety/design guidance was removed: {missing}"
