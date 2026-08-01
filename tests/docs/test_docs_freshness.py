"""Doc-lint: mechanical freshness invariants for the docs-as-product gate (E2).

No LLM, no fuzzy matching — every check below is a plain string/path
comparison against the live tree. Intentionally narrow where a broader
check would produce false positives (see docstrings per test).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import stat
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from functools import cache
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_files() -> list[str]:
    """Return Git-tracked repo-relative paths; missing Git evidence is fatal."""
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def _read(path: Path) -> str:
    """Read required UTF-8 evidence; missing or invalid input must fail."""
    return path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    """Parse the flat key/value subset used by canonical docs front matter."""

    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return result
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip()
    return {}


def test_design_system_release_markers_are_one_version() -> None:
    design_root = REPO_ROOT / "docs" / "design-system"
    version = _read(design_root / "VERSION").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)

    versioned = (
        design_root / "README.md",
        design_root / "MANIFEST.md",
        design_root / "CHANGELOG.md",
        design_root / "GUI_MIGRATION_INVENTORY.md",
        design_root / "cryodaq-primitives" / "tray-status.md",
    )
    for path in versioned:
        assert _frontmatter(_read(path)).get("version") == version, path

    assert f"**Current design-system version:** `{version}`" in _read(design_root / "README.md")
    assert f"**Scope:** Design system v{version}" in _read(design_root / "MANIFEST.md")
    assert re.search(rf"^## \[{re.escape(version)}\]", _read(design_root / "CHANGELOG.md"), re.MULTILINE)
    assert f"design-system v{version} corpus-wide" in _read(design_root / "GUI_MIGRATION_INVENTORY.md")

    versioning = _read(design_root / "governance" / "versioning.md")
    for path in (design_root / "VERSION", *versioned):
        relative = path.relative_to(REPO_ROOT).as_posix()
        assert relative in versioning, relative

    governance_rules = _read(design_root / "rules" / "governance-rules.md")
    assert f"**Current version:** v{version}" in governance_rules
    assert f"Current v{version} state" in governance_rules


def test_canonical_design_system_artifacts_and_markdown_references_are_tracked() -> None:
    tracked = set(_tracked_files())
    design_root = REPO_ROOT / "docs" / "design-system"
    required = {
        "docs/design-system/README.md",
        "docs/design-system/MANIFEST.md",
        "docs/design-system/CHANGELOG.md",
        "docs/design-system/VERSION",
        "docs/design-system/GUI_MIGRATION_INVENTORY.md",
        "docs/design-system/cryodaq-primitives/tray-status.md",
    }

    references: set[str] = set()
    for source_name in ("README.md", "MANIFEST.md"):
        source = _read(design_root / source_name)
        spans = _BACKTICK_RE.findall(source)
        spans.extend(re.findall(r"\]\(([^)]+\.md(?:#[^)]+)?)\)", source))
        for span in spans:
            target = span.split("#", 1)[0]
            if not target.endswith(".md") or "://" in target or any(marker in target for marker in "*?["):
                continue
            if target.startswith("docs/design-system/"):
                relative = target
            elif target.startswith(
                (
                    "tokens/",
                    "rules/",
                    "components/",
                    "cryodaq-primitives/",
                    "patterns/",
                    "accessibility/",
                    "governance/",
                    "adr/",
                )
            ) or target in {
                "README.md",
                "MANIFEST.md",
                "CHANGELOG.md",
                "GUI_MIGRATION_INVENTORY.md",
                "ANTI_PATTERNS.md",
            }:
                relative = f"docs/design-system/{target}"
            else:
                continue
            references.add(relative)

    expected = required | references
    missing_files = sorted(path for path in expected if not (REPO_ROOT / path).is_file())
    untracked = sorted(expected - tracked)
    assert not missing_files, "canonical design-system references are missing:\n" + "\n".join(missing_files)
    assert not untracked, "canonical design-system artifacts/references are not Git-tracked:\n" + "\n".join(untracked)


def test_operator_contracts_do_not_reintroduce_stale_harmful_semantics() -> None:
    paths = (
        "ROADMAP.md",
        "docs/MONTANA_REFACTOR_REPORT.md",
        "docs/design-system/cryodaq-primitives/phase-stepper.md",
        "docs/design-system/cryodaq-primitives/experiment-card.md",
        "docs/design-system/cryodaq-primitives/experiment-panel.md",
        "docs/design-system/cryodaq-primitives/operator-log-panel.md",
        "docs/design-system/cryodaq-primitives/bottom-status-bar.md",
        "docs/design-system/cryodaq-primitives/keithley-panel.md",
        "docs/design-system/rules/color-rules.md",
        "docs/design-system/tokens/colors.md",
    )
    corpus = "\n".join(_read(REPO_ROOT / path) for path in paths)
    forbidden = (
        "emergency-off hold-to-confirm is retained",
        "active=STATUS_OK not ACCENT",
        "current phase pill border (green highlight)",
        "DS primary variant (STATUS_OK / ON_PRIMARY)",
        "Normal chrome + STATUS_OK mode badge",
        "| `running` | STATUS_OK | Active operation |",
        "State badge «ВКЛ» STATUS_OK",
        "Focus/selected/active states use ACCENT or STATUS_OK",
        "safety READY",
    )
    assert not [phrase for phrase in forbidden if phrase in corpus]

    roadmap = _read(REPO_ROOT / "ROADMAP.md")
    f36_4 = roadmap.split("### F36.4", 1)[1].split("### F36.5", 1)[0]
    assert "belongs to F37" in f36_4
    assert "proves at least 100 devices" not in f36_4
    f37 = roadmap.split("**F37", 1)[1].split("**F8", 1)[0]
    for term in ("100+ sensors", "4K", "virtualized", "semantic zoom"):
        assert term in f37

    color_rules = _read(REPO_ROOT / "docs/design-system/rules/color-rules.md")
    rule_color_005 = color_rules.split("## RULE-COLOR-005", 1)[1].split("## RULE-COLOR-006", 1)[0]
    good_example = rule_color_005.split("**Example (good):**", 1)[1].split("**Example (bad):**", 1)[0]
    assert "theme.STATUS_CAUTION" in good_example
    assert "theme.STATUS_WARNING" not in good_example


def test_design_system_rule_references_resolve() -> None:
    design_root = REPO_ROOT / "docs" / "design-system"
    definitions: set[str] = set()
    references: set[str] = set()

    for path in sorted(design_root.rglob("*.md")):
        text = _read(path)
        definitions.update(re.findall(r"^## (RULE-[A-Z0-9]+-\d{3})\b", text, re.MULTILINE))
        references.update(re.findall(r"\bRULE-[A-Z0-9]+-\d{3}\b", text))

    assert sorted(references - definitions) == []


def test_bottom_status_bar_spec_matches_live_setter_contract() -> None:
    setter_re = re.compile(r"^    def (set_[a-z_]+)\(", re.MULTILINE)
    source = _read(REPO_ROOT / "src/cryodaq/gui/shell/bottom_status_bar.py")
    spec = _read(REPO_ROOT / "docs/design-system/cryodaq-primitives/bottom-status-bar.md")

    assert set(setter_re.findall(spec)) == set(setter_re.findall(source))
    for marker in ("Лаунчер", "Диск", "изм/с"):
        assert marker in spec
    assert "class StatusItem" not in spec


def test_operator_manual_matches_current_runtime_authority_boundaries() -> None:
    manual = _read(REPO_ROOT / "docs/operator_manual.md")
    normalized = re.sub(r"\s+", " ", manual)

    alarm = normalized.split("### 4.3. Тревоги", 1)[1].split("### 4.4. Служебный лог", 1)[0]
    assert "Отдельного age/TTL-gate для alarm snapshot сейчас нет" in alarm
    assert "GUI отправляет пустые `operator` и `reason`" in alarm
    assert "Квитирование доступно только при свежем подключении" not in alarm

    conductivity = normalized.split("### 4.8. Теплопроводность", 1)[1].split("## 5. Эксперименты", 1)[0]
    for required in (
        "автоматически не блокирует финализацию",
        "отключаются и `Старт`, и `Стоп`",
        "Только после него состояние возвращается в `idle`",
    ):
        assert required in conductivity
    assert "Stop остаётся доступным" not in conductivity

    knowledge = normalized.split("## 12. База знаний", 1)[1]
    for required in (
        "принадлежат отдельному процессу `cryodaq-assistant`",
        "observational-only границе помощника",
        "Restart engine не запускает и не перестраивает assistant index",
    ):
        assert required in knowledge
    assert "Альтернативно — restart engine" not in knowledge
    assert "«Обновить индекс» в GUI или restart engine" not in knowledge

    tray = normalized.split("На Windows доступна иконка в системном трее", 1)[1].split("## 4. Основные поверхности", 1)[
        0
    ]
    assert "alarm_count` в launcher/tray" in tray
    assert "незавершённом shutdown красный имеет отдельное значение" in tray
    assert "authoritative alarm/snapshot wiring" not in tray


def test_public_docs_keep_provider_machine_and_secret_boundaries() -> None:
    public_paths = (
        "README.md",
        "README.ru.md",
        "PROJECT_STATUS.md",
        "ROADMAP.md",
        "docs/MONTANA_REFACTOR_REPORT.md",
        "docs/architecture.md",
        "docs/lab_verification_checklist.md",
    )
    corpus = "\n".join(_read(REPO_ROOT / path) for path in public_paths)
    for private_or_machine_specific in (
        "Fable",
        "fable",
        "/mnt/c/Users/3fall",
        r"C:\Users\3fall",
        "CryoDAQ-Ubuntu-3",
    ):
        assert private_or_machine_specific not in corpus

    notifications = _read(REPO_ROOT / "config/notifications.yaml")
    assert "YOUR_BOT_TOKEN_HERE" in notifications
    assert "notifications.local.yaml" in corpus
    assert "native-ext4" in corpus and "drvfs" in corpus


def test_experiment_timeout_is_documented_as_unknown_outcome_and_open_gate() -> None:
    architecture = _read(REPO_ROOT / "docs/architecture.md")
    report = _read(REPO_ROOT / "docs/MONTANA_REFACTOR_REPORT.md")
    status = _read(REPO_ROOT / "PROJECT_STATUS.md")
    corpus = "\n".join((architecture, report, status))

    for required in (
        "outcome unknown",
        "timeout-then-late-commit",
        "experiment_status",
        "post-commit",
    ):
        assert all(required in document for document in (architecture, report, status))
    normalized_architecture = re.sub(r"\s+", " ", architecture)
    assert "must not retry a mutating experiment command automatically or blindly" in normalized_architecture
    assert "open final-candidate gate" in architecture
    assert "automatic or blind retry is allowed" not in corpus


# Empirically verified against the current tree (2026-07-25): zero false
# positives across src/cryodaq/gui/**/*.py and exact coverage of the nine
# traced presentation instances plus the shared zmq_client.py transport
# contract. This is NOT a theoretically complete symbol set — there is no
# single naming convention shared by every instance (e.g. keithley_panel.py
# uses "unknown_outcome" word order in some identifiers and "outcome_unknown"
# in others; quick_log_block.py/phase_aware_widget.py carry no "outcome"
# substring at all, only a bare "unknown" state value plus their setter
# names). A sufficiently novel future spelling (e.g. a hypothetical state
# string like "ambiguous" instead of "unknown") would evade every pattern
# below and is a known, recorded gap, not a claimed guarantee. See
# docs/design-system/patterns/command-outcome-unknown.md "Enforcement".
_OUTCOME_UNKNOWN_SYMBOL_PATTERN = re.compile(
    r"outcome_unknown"
    r"|unknown_outcome"
    r"|show_unknown"
    r"|set_submission_state"
    r"|set_operation_state"
    r"|ИСХОД НЕИЗВЕСТЕН"
)


def test_outcome_unknown_gui_instances_are_documented_in_design_system() -> None:
    """Every GUI file carrying the outcome-unknown mutation-result pattern must
    be named in patterns/command-outcome-unknown.md. A new panel implementing
    this pattern without updating that document's instance table fails here,
    per ADR-003 (mistake-to-enforcement): the design-system table must not be
    allowed to silently drift out of sync with the code it documents.
    """
    gui_root = REPO_ROOT / "src" / "cryodaq" / "gui"
    matched_files = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in gui_root.rglob("*.py")
        if "__pycache__" not in path.parts and _OUTCOME_UNKNOWN_SYMBOL_PATTERN.search(_read(path))
    )
    assert matched_files, "expected the known outcome-unknown instances to still be present"

    doc = _read(REPO_ROOT / "docs" / "design-system" / "patterns" / "command-outcome-unknown.md")
    undocumented = [path for path in matched_files if Path(path).name not in doc]
    assert not undocumented, (
        "GUI file(s) carry the outcome-unknown pattern's known symbol vocabulary "
        "but are not named in docs/design-system/patterns/command-outcome-unknown.md: "
        f"{undocumented}"
    )


def _normalize_contract_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


EXPECTED_POST_LOG_SETTLEMENT_ROWS = {
    "409": (
        """A definite non-commit. The response contains `caller_request_id`, copied
        from the submitted header, and an exact boolean `retry_safe`. It proves
        non-commit with either `committed=false` or `commit_state="not_committed"`;
        it is not a `publication_state="published"` or `"pending"` receipt.""",
        """Retain the same caller-owned key. Retry only when `retry_safe` is `true`;
        when it is `false`, resolve the rejection without blindly resubmitting or
        replacing the key.""",
    ),
    "502": (
        """Outcome unknown: neither success nor definite failure. A structured
        unknown-settlement body has `commit_state="unknown"`, `retry_safe=false`,
        `caller_request_id`, and `engine_settlement`. `engine_settlement` is bounded,
        filtered evidence only: it may be empty and may retain only safe
        status/correlation fields (`ok`, `committed`, `retry_safe`,
        `publication_state`, `commit_state`, `delivery_state`, `error_code`, `proto`,
        `schema`, and a matching `request_id`). It is not an authoritative settlement
        and cannot turn the 502 into a success or non-commit. A forwarding/transport
        exception can instead be FastAPI's generic 502 detail body and provides none
        of those structured fields.""",
        """Do not blindly retry and do not invent a new key. Reconcile using the same
        caller-owned identity; a generic transport 502 is unknown for the same
        reason.""",
    ),
    "503": (
        """The command is committed but required broker publication remains pending.
        The accepted receipt has `committed=true`, `retry_safe=false`,
        `publication_state="pending"`, and `caller_request_id`; it also carries the
        persisted entry/commit receipt and the pending diagnostic.""",
        """Do not issue a new mutation. Reconcile, or retry that reconciliation, with
        the same key until publication settles.""",
    ),
}

EXPECTED_POST_LOG_SETTLEMENT_PROSE = """
The `Idempotency-Key` belongs to the caller, not to one HTTP attempt. Preserve
it with the original payload until the submission is settled; never create a
new key to work around a non-2xx response. The status code is the first
settlement boundary:

Only accepted completion receipts make `publication_state` authoritative:
`"published"` at HTTP 200 or `"pending"` at HTTP 503. The HTTP 200 receipt
returns the caller key as `request_id`; the non-2xx bodies above use
`caller_request_id` for caller correlation. Do not infer a settlement from a
missing field or from an unrecognized response shape.

Clients cannot supply `author`, `source`, `request_id` in JSON,
`experiment_unbound`, or a generic engine command through these routes.
Reserved system tags are rejected rather than accepted as operator metadata.
"""

POST_LOG_SETTLEMENT_PROSE_ANCHOR = "Only accepted completion receipts make `publication_state` authoritative:"


def _normalized_post_log_settlement_policy(protocol: str) -> tuple[dict[str, tuple[str, str]], str]:
    """Return the exact table cells and exact non-table prose for the settlement contract."""

    match = re.search(
        r"(?ms)^### POST /api/v1/log settlement and retry\s*$\n(?P<section>.*?)(?=^## |\Z)",
        protocol,
    )
    assert match, "protocol omits the normative POST /log settlement section"
    section = match.group("section")
    table_lines = [line for line in section.splitlines() if line.startswith("|")]
    table = [
        tuple(_normalize_contract_text(cell) for cell in line.strip().strip("|").split("|")) for line in table_lines
    ]
    assert table[:2] == [
        ("HTTP status", "Proven settlement and response fields to interpret", "Safe next action"),
        ("---", "---", "---"),
    ], "settlement table header is not canonical"
    rows = {status: (truth, action) for status, truth, action in table[2:]}
    assert len(rows) == len(table[2:]), "settlement table has duplicate status rows"
    assert set(rows) == {"409", "502", "503"}, "settlement table must contain exactly 409, 502, and 503"
    prose = "\n".join(line for line in section.splitlines() if not line.startswith("|"))
    return rows, _normalize_contract_text(prose)


def _assert_post_log_settlement_policy(protocol: str) -> None:
    """Require the complete, readable canonical POST /log settlement contract."""

    rows, prose = _normalized_post_log_settlement_policy(protocol)
    expected_rows = {
        status: tuple(_normalize_contract_text(cell) for cell in cells)
        for status, cells in EXPECTED_POST_LOG_SETTLEMENT_ROWS.items()
    }
    assert rows == expected_rows, "settlement table cells are not the canonical contract"
    assert prose == _normalize_contract_text(EXPECTED_POST_LOG_SETTLEMENT_PROSE), (
        "settlement prose outside the table is not the canonical contract"
    )


@pytest.mark.parametrize(
    ("probe", "old", "new"),
    (
        (
            "unsafe For-status 409 guidance",
            POST_LOG_SETTLEMENT_PROSE_ANCHOR,
            "For status 409, retry even when retry_safe=false.\n\n" + POST_LOG_SETTLEMENT_PROSE_ANCHOR,
        ),
        (
            "unsafe For-status 502 guidance",
            POST_LOG_SETTLEMENT_PROSE_ANCHOR,
            "For status 502, blindly retry with a new key.\n\n" + POST_LOG_SETTLEMENT_PROSE_ANCHOR,
        ),
        (
            "unsafe For-status 503 guidance",
            POST_LOG_SETTLEMENT_PROSE_ANCHOR,
            "For status 503, issue a new mutation.\n\n" + POST_LOG_SETTLEMENT_PROSE_ANCHOR,
        ),
        (
            "safe negation is noncanonical rather than regex-misclassified",
            POST_LOG_SETTLEMENT_PROSE_ANCHOR,
            "For status 502, do not blindly retry.\n\n" + POST_LOG_SETTLEMENT_PROSE_ANCHOR,
        ),
        ("409 omits caller_request_id", "`caller_request_id`, copied from the submitted header, and ", ""),
        ("503 omits caller_request_id", ", and `caller_request_id`; it also carries", "; it also carries"),
        (
            "502 promises request_id for every response",
            "`caller_request_id`, and `engine_settlement`",
            "`caller_request_id`, `request_id` for every 502 response, and `engine_settlement`",
        ),
        ("503 appends retry_safe=true", "and the pending diagnostic.", "and the pending diagnostic. retry_safe=true."),
    ),
)
def test_public_rest_docs_settlement_guard_rejects_noncanonical_contract(probe: str, old: str, new: str) -> None:
    protocol = _read(REPO_ROOT / "docs/protocol.md")
    assert old in protocol, probe
    mutated = protocol.replace(old, new, 1)
    with pytest.raises(AssertionError, match="canonical"):
        _assert_post_log_settlement_policy(mutated)


def test_public_rest_docs_require_explicit_scope_and_strict_json() -> None:
    detailed_paths = (
        "docs/protocol.md",
        "docs/deployment.md",
        "docs/operator_manual.md",
    )
    summary_paths = ("README.md", "README.ru.md")

    for path in (*detailed_paths, *summary_paths):
        text = _read(REPO_ROOT / path)
        for required in (
            "/api/v1/log",
            "experiment_id",
            "experiment_unbound",
            "request_id",
            "null",
        ):
            assert required in text, f"{path} omits REST contract term {required!r}"

    protocol = _read(REPO_ROOT / "docs/protocol.md")
    normalized_protocol = re.sub(r"\s+", " ", protocol)
    assert "32-character lowercase hexadecimal" in normalized_protocol
    assert "never attached to whichever experiment happens" in normalized_protocol
    assert "NaN" in protocol and "+Infinity" in protocol and "-Infinity" in protocol

    for path in (*detailed_paths, *summary_paths):
        text = _read(REPO_ROOT / path)
        assert "Idempotency-Key" in text, f"{path} omits the caller-owned retry header"
        assert "request_id" in text and "JSON" in text, f"{path} omits request_id JSON guidance"

    assert "The web process creates one 32-character lowercase" not in protocol
    assert "The caller supplies `Idempotency-Key`" in protocol
    assert "The caller supplies `Idempotency-Key`" in _read(REPO_ROOT / "README.md")
    for path in ("docs/deployment.md", "docs/operator_manual.md"):
        assert "Клиент передаёт `Idempotency-Key`" in _read(REPO_ROOT / path)
    russian_readme = _read(REPO_ROOT / "README.ru.md")
    assert "Клиент передаёт" in russian_readme
    assert "Клиенты не передают `request_id` в JSON" in russian_readme
    assert "сервер, он же создаёт один\n`request_id`" not in russian_readme

    _assert_post_log_settlement_policy(protocol)

    settlement_anchor = "protocol.md#post-apiv1log-settlement-and-retry"
    for path in (*detailed_paths[1:], *summary_paths):
        assert settlement_anchor in _read(REPO_ROOT / path), f"{path} omits the settlement-contract cross-reference"


# ---------------------------------------------------------------------------
# (a) every console script in pyproject.toml [project.scripts] is named in
# docs/quickstart.md or docs/operator_manual.md. Word-boundary match (not
# preceded/followed by a word char or hyphen) so "cryodaq" doesn't
# false-positive off "cryodaq-engine".
# ---------------------------------------------------------------------------


def test_console_scripts_documented_in_quickstart_or_operator_manual():
    scripts = sorted(_pyproject()["project"]["scripts"])
    text = _read(REPO_ROOT / "docs" / "quickstart.md") + _read(REPO_ROOT / "docs" / "operator_manual.md")
    missing = [s for s in scripts if not re.search(rf"(?<![\w-]){re.escape(s)}(?![\w-])", text)]
    assert not missing, (
        "Console scripts from pyproject.toml [project.scripts] not documented "
        "in docs/quickstart.md or docs/operator_manual.md:\n" + "\n".join(missing)
    )


# ---------------------------------------------------------------------------
# (b) every top-level config/*.yaml file (git-tracked; "*.local.yaml"
# machine overrides are gitignored and excluded by construction, since
# _tracked_files() only returns tracked paths) is mentioned in at least one
# tracked doc. Non-recursive by design: config/themes/*.yaml and
# config/experiment_templates/*.yaml are documented via the glob itself
# (existing convention in README.md), not per-file.
# ---------------------------------------------------------------------------


def test_top_level_config_yaml_mentioned_in_some_doc():
    tracked = _tracked_files()
    config_yaml = sorted(p for p in tracked if p.startswith("config/") and p.count("/") == 1 and p.endswith(".yaml"))
    assert config_yaml, "expected at least one top-level config/*.yaml file"
    all_docs_text = "".join(_read(REPO_ROOT / p) for p in tracked if p.endswith(".md"))
    missing = [c for c in config_yaml if c not in all_docs_text]
    assert not missing, "config/*.yaml files not mentioned in any tracked doc:\n" + "\n".join(missing)


# ---------------------------------------------------------------------------
# (c) CHANGELOG.md's newest versioned entry (skipping "## [Unreleased]")
# must equal pyproject.toml's [project] version — catches a release that
# bumped one file but not the other.
# ---------------------------------------------------------------------------


def test_changelog_top_version_matches_pyproject():
    text = _read(REPO_ROOT / "CHANGELOG.md")
    versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    assert versions, "CHANGELOG.md has no '## [X.Y.Z]' version heading"
    pyproject_version = _pyproject()["project"]["version"]
    assert versions[0] == pyproject_version, (
        f"CHANGELOG.md top version [{versions[0]}] != pyproject.toml version [{pyproject_version}]"
    )


# ---------------------------------------------------------------------------
# (d) no tracked doc references a repo-relative path (in backticks) that
# does not exist on disk. Mechanical, deliberately narrow to avoid false
# positives:
#
# - only paths starting under docs/, config/, src/, tests/, tools/,
#   scripts/, build_scripts/, tsp/ (source-tree-like; NOT data/ or logs/,
#   which are runtime output dirs that legitimately don't exist in a fresh
#   checkout)
# - CHANGELOG.md is exempt as a source doc — it is an append-only
#   historical ledger, expected to reference files removed in later
#   releases (e.g. the Alarm Engine v1 config)
# - docs/design-system/** is exempt as a source of references — a
#   separately-governed UI spec (see docs/design-system/governance/) whose
#   component-file citations predate the MainWindowV2 refactor in places;
#   reconciling that subtree is out of scope for this gate
# - glob/placeholder markers (* < > { }) are skipped — e.g.
#   "config/themes/*.yaml", "data/experiments/<id>/metadata.json"
# - any path containing ".local." is skipped — gitignored machine-local
#   override files that intentionally don't exist until an operator copies
#   them from a ".example" template
# - a trailing ":N" or ":N-M" line-range citation is stripped before the
#   existence check
# - the final path segment must end in a lowercase alnum "extension"
#   (1-6 chars) — filters out dotted Python references like
#   "base.InstrumentDriver" that are not file paths at all
# ---------------------------------------------------------------------------

_PATH_PREFIXES = ("docs/", "config/", "src/", "tests/", "tools/", "scripts/", "build_scripts/", "tsp/")
_EXEMPT_SOURCE_PREFIXES: tuple[str, ...] = ()
_LINE_REF_RE = re.compile(r":\d+(-\d+)?$")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def _is_path_candidate(span: str) -> bool:
    if not any(span.startswith(p) for p in _PATH_PREFIXES):
        return False
    if any(ch in span for ch in "*<>{}"):
        return False
    if ".local." in span:
        return False
    last_seg = span.rsplit("/", 1)[-1]
    if "." not in last_seg:
        return False
    ext = _LINE_REF_RE.sub("", last_seg.rsplit(".", 1)[-1])
    return bool(re.fullmatch(r"[a-z0-9]{1,6}", ext))


def test_no_dead_repo_paths_referenced_in_docs():
    dead: dict[str, list[str]] = {}
    for p in _tracked_files():
        if not p.endswith(".md") or p == "CHANGELOG.md":
            continue
        if p.startswith(_EXEMPT_SOURCE_PREFIXES):
            continue
        text = _read(REPO_ROOT / p)
        for span in _BACKTICK_RE.findall(text):
            if not _is_path_candidate(span):
                continue
            target = _LINE_REF_RE.sub("", span)
            if not (REPO_ROOT / target).exists():
                dead.setdefault(span, []).append(p)
    assert not dead, "Dead repo-relative paths referenced in docs:\n" + "\n".join(
        f"{path!r} in {sorted(set(srcs))}" for path, srcs in sorted(dead.items())
    )


# ---------------------------------------------------------------------------
# G4-DOCS-001: building-agent instructions use resolvable citations and every
# acceptance procedure exposes the bounds and evidence needed to run it.
# This is deliberately filesystem-only: it also runs in an exported candidate.
# ---------------------------------------------------------------------------

_G4_DOCS = (
    "AGENTS.md",
    "docs/new_lab_adaptation.md",
    "docs/new_lab_acceptance_checklist.md",
    "docs/quickstart.md",
)
_G4_REFERENCE_RE = re.compile(r"\[\[ref:([^\]\n]+)\]\]")
_G4_UNMARKED_REFERENCE_RE = re.compile(r"(?<![\w/])((?:src|tests|scripts)(?:/[\w.-]+)*\.py(?:::[A-Za-z_][\w.]*)?)")
_G4_LEGACY_LINE_RE = re.compile(r"(?:[\w./-]+\.(?:py|ya?ml|toml|md)|\.gitignore):\d+")
_G4_CONSOLE_COMMAND_RE = re.compile(r"(?m)^\s*(cryodaq(?:-[\w]+)*)\b")
_G4_PROCEDURE_RE = re.compile(r"<!-- G4-PROCEDURES\n(.*?)\n-->", re.DOTALL)
_G4_BOUND_RE = re.compile(
    r"(?:0|[1-9]\d*)(?:\.\d+)?(?:\s+(?:\+|\d+|[A-Za-z][A-Za-z0-9/-]*|\d+(?:\.\d+)?[A-Za-z][A-Za-z0-9/-]*))+"
)
_G4_ID_DECLARATION_RE = re.compile(r"(?m)^\s*(?:#\s+|contract_id:\s*|-\s+id:\s*)([A-Z][A-Z0-9-]*-\d{3})(?=[:\s]|$)")
_G4_ID_DECLARATION_PATHS = (
    "governance/agent_preventions.yaml",
    "tests/docs/test_docs_freshness.py",
)
_G4_PROCEDURE_FIELDS = (
    "preconditions",
    "target",
    "bound",
    "abort",
    "cleanup",
    "evidence",
    "decision_owner",
    "result",
)


def _g4_symbols(path: Path) -> set[str]:
    """Return top-level names plus class-qualified methods in one source file."""

    tree = ast.parse(_read(path), filename=str(path))
    symbols: set[str] = set()

    def add_nodes(nodes: list[ast.stmt], prefix: str = "") -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{node.name}"
                symbols.add(name)
                if isinstance(node, ast.ClassDef):
                    add_nodes(node.body, f"{name}.")
            elif not prefix and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        symbols.add(target.id)

    add_nodes(tree.body)
    return symbols


def _g4_yaml_key(root: Path, reference: str) -> str | None:
    path_text, separator, key_path = reference.partition("::")
    if not separator or not path_text.endswith((".yaml", ".yml")) or not key_path:
        return "must be yaml-file::key.path"
    path = root / path_text
    if not path.is_file():
        return f"file does not exist: {path_text}"
    value: object = yaml.safe_load(_read(path))
    for key in key_path.split("."):
        if not isinstance(value, dict) or key not in value:
            return f"key does not resolve: {reference}"
        value = value[key]
    return None


def _g4_declared_ids(root: Path) -> set[str]:
    """Read stable IDs from their declaration sites, never from citations."""

    return {
        stable_id
        for relative in _G4_ID_DECLARATION_PATHS
        for stable_id in _G4_ID_DECLARATION_RE.findall(_read(root / relative))
    }


def _g4_is_source_controlled(root: Path, relative_path: str) -> bool:
    """Return whether the path exists in the committed tree at HEAD.

    Resolved against the BOUND TREE rather than the index, which closes two ways
    the earlier `git ls-files --error-unmatch` form could lie.

    Pathspec magic: `ls-files` interprets its argument as a pathspec, so a future
    `requires:Make*|status:present` reference was satisfied by the tracked
    `Makefile` even though nothing named `Make*` is tracked -- measured. The
    replacement uses `ls-tree` with literal pathspec semantics.

    Index availability: `ls-files` returns 1 both for a genuinely untracked path
    and for a missing or unreadable `.git/index` (including an inherited
    `GIT_INDEX_FILE` pointing nowhere), so unavailable evidence read as "absent"
    and let a `status:absent` reference pass. HEAD is verified independently
    first, so an unresolvable HEAD raises instead of being mistaken for absence.

    Replacement refs: Git commands ordinarily honor `refs/replace/*`, so a local
    `git replace HEAD HEAD^` can substitute an ancestor tree and turn a tracked
    prerequisite into apparent absence. Every evidence lookup disables object
    replacement so the claim remains bound to the raw commit named by HEAD.

    A committed tree is also the right authority for the claim being checked: a
    `status:` declaration is about a FRESH CHECKOUT, not about an index state.
    """

    root = root.resolve()
    git_env = os.environ.copy()
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
    ):
        git_env.pop(key, None)
    for key in tuple(git_env):
        if key == "GIT_CONFIG_COUNT" or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            git_env.pop(key, None)

    repository = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        env=git_env,
    )
    if repository.returncode or Path(repository.stdout.strip()).resolve() != root:
        raise RuntimeError(f"{root} is not the resolved Git repository, so source-control evidence is unavailable")

    head = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-C",
            str(root),
            "rev-parse",
            "--verify",
            "--quiet",
            "HEAD^{commit}",
        ],
        capture_output=True,
        text=True,
        env=git_env,
    )
    if head.returncode:
        raise RuntimeError(f"HEAD does not resolve in {root}, so source-control evidence is unavailable")
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-C",
            str(root),
            "--literal-pathspecs",
            "ls-tree",
            "-z",
            "--full-tree",
            "HEAD",
            "--",
            relative_path,
        ],
        capture_output=True,
        env=git_env,
    )
    if result.returncode:
        raise RuntimeError(f"committed tree lookup failed in {root}, so source-control evidence is unavailable")
    if not result.stdout:
        return False
    entries = result.stdout.split(b"\0")
    if entries[-1] == b"":
        entries.pop()
    expected = relative_path.encode("utf-8")
    paths = [entry.split(b"\t", 1)[1] for entry in entries if b"\t" in entry]
    if len(entries) != 1 or paths != [expected]:
        raise RuntimeError(f"committed tree lookup returned ambiguous evidence for {relative_path}")
    return True


def _g4_reference_error(
    root: Path,
    reference: str,
    *,
    source_controlled: Callable[[str], bool] | None = None,
) -> str | None:
    if reference.startswith("make:"):
        target, separator, requirement = reference[5:].partition("|requires:")
        required_path, status_separator, status = requirement.partition("|status:")
        makefile = root / "Makefile"
        if not target or not separator or not status_separator or status not in {"present", "absent"}:
            return f"make reference lacks a checkable prerequisite: {reference}"
        if not re.search(rf"(?m)^{re.escape(target)}:\s*$", _read(makefile)):
            return f"make target does not exist: {target}"
        exists = (
            source_controlled(required_path)
            if source_controlled is not None
            else _g4_is_source_controlled(root, required_path)
        )
        if exists != (status == "present"):
            return f"make prerequisite status differs: {required_path} is {'present' if exists else 'absent'}"
        return None
    if reference.startswith("command:"):
        command = shlex.split(reference[8:])
        if not command or command[0] not in _pyproject()["project"]["scripts"]:
            return f"command is not a project console script: {reference}"
        return None
    if reference.startswith("test:"):
        reference = reference[5:]
    if reference.startswith("id:"):
        stable_id = reference[3:]
        if not re.fullmatch(r"[A-Z][A-Z0-9-]*-\d{3}", stable_id):
            return f"invalid stable ID: {reference}"
        return None if stable_id in _g4_declared_ids(root) else f"stable ID is not declared: {stable_id}"
    if reference.endswith((".yaml", ".yml")):
        return None if (root / reference).is_file() else f"file does not exist: {reference}"
    if ".yaml::" in reference or ".yml::" in reference:
        return _g4_yaml_key(root, reference)

    path_text, separator, symbol = reference.partition("::")
    if not separator and path_text.endswith(".py"):
        return None if (root / path_text).is_file() else f"file does not exist: {path_text}"
    if not separator or not path_text.endswith(".py") or not symbol:
        return f"must be path::qualified.symbol, yaml-file::key.path, command, make target, or stable ID: {reference}"
    path = root / path_text
    if not path.is_file():
        return f"file does not exist: {path_text}"
    if symbol not in _g4_symbols(path):
        return f"symbol does not exist: {reference}"
    return None


def _g4_procedures(text: str) -> dict[str, dict[str, str]]:
    match = _G4_PROCEDURE_RE.search(text)
    if not match:
        raise AssertionError("G4 procedure declaration block is missing")
    procedures: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw_line in match.group(1).splitlines():
        if not raw_line.strip():
            continue
        gate = re.fullmatch(r"(G\d\.\d):", raw_line)
        if gate:
            current = procedures.setdefault(gate.group(1), {})
            continue
        field, separator, value = raw_line.strip().partition(": ")
        if current is None or not separator:
            raise AssertionError(f"invalid G4 procedure declaration line: {raw_line}")
        current[field] = value
    return procedures


def _validate_g4_docs(
    root: Path,
    overrides: dict[str, str] | None = None,
    *,
    source_controlled: Callable[[str], bool] | None = None,
) -> None:
    """Validate G4 documents; make prerequisites require Git source-control evidence."""

    overrides = overrides or {}
    documents = {name: overrides.get(name, _read(root / name)) for name in _G4_DOCS}
    errors: list[str] = []
    for name, text in documents.items():
        for legacy in _G4_LEGACY_LINE_RE.findall(text):
            errors.append(f"{name}: line-number citation is forbidden: {legacy}")
        for reference in _G4_REFERENCE_RE.findall(text):
            if error := _g4_reference_error(root, reference, source_controlled=source_controlled):
                errors.append(f"{name}: {error}")
        unmarked = _G4_REFERENCE_RE.sub("", text)
        for reference in _G4_UNMARKED_REFERENCE_RE.findall(unmarked):
            if error := _g4_reference_error(root, reference):
                errors.append(f"{name}: unmarked executable reference: {error}")
        for command in _G4_CONSOLE_COMMAND_RE.findall(text):
            if command not in _pyproject()["project"]["scripts"]:
                errors.append(f"{name}: command is not a project console script: {command}")

    checklist = documents["docs/new_lab_acceptance_checklist.md"]
    procedures = _g4_procedures(checklist)
    gate_ids = set(re.findall(r"\*\*(G\d\.\d)", checklist)) | {"G6.1"}
    missing = sorted(gate_ids - procedures.keys())
    extra = sorted(procedures.keys() - gate_ids)
    if missing:
        errors.append(f"procedure declarations missing for: {', '.join(missing)}")
    if extra:
        errors.append(f"procedure declarations have unknown gates: {', '.join(extra)}")
    for gate, fields in sorted(procedures.items()):
        for field in _G4_PROCEDURE_FIELDS:
            if not fields.get(field, "").strip():
                errors.append(f"{gate}: procedure field is missing: {field}")
        if not _G4_BOUND_RE.fullmatch(fields.get("bound", "").strip()):
            errors.append(f"{gate}: bound must be a quantified bound expression")
        result = fields.get("result", "")
        if result not in {"SOFTWARE-PROVABLE", "EXTERNALLY_EVIDENCED", "PHYSICAL"}:
            errors.append(f"{gate}: invalid result class: {result}")
    assert not errors, "G4 documentation guard failed:\n" + "\n".join(errors)


def test_g4_executable_references_and_procedure_declarations() -> None:
    _validate_g4_docs(REPO_ROOT)


@pytest.mark.parametrize(
    ("in_git_index", "on_disk", "declared_status", "opposite_status"),
    (
        (False, True, "absent", "present"),
        (True, False, "present", "absent"),
    ),
)
def test_g4_rejects_make_prerequisite_status_not_matching_source_control(
    tmp_path: Path,
    in_git_index: bool,
    on_disk: bool,
    declared_status: str,
    opposite_status: str,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "Makefile").write_text("bootstrap-predictor:\n", encoding="utf-8")
    required_path = "predictor_model.json"
    prerequisite = tmp_path / required_path

    _commit = ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q"]
    subprocess.run([*_commit, "-m", "seed", "--allow-empty"], cwd=tmp_path, check=True)
    if in_git_index:
        prerequisite.write_text("model", encoding="utf-8")
        subprocess.run(["git", "add", "-f", required_path], cwd=tmp_path, check=True)
        subprocess.run([*_commit, "-m", "track"], cwd=tmp_path, check=True)
    if not on_disk:
        prerequisite.unlink()
    elif not in_git_index:
        prerequisite.write_text("model", encoding="utf-8")

    assert prerequisite.exists() is on_disk
    assert _g4_is_source_controlled(tmp_path, required_path) is in_git_index

    reference = f"make:bootstrap-predictor|requires:{required_path}|status:{declared_status}"
    assert _g4_reference_error(tmp_path, reference) is None

    opposite_reference = f"make:bootstrap-predictor|requires:{required_path}|status:{opposite_status}"
    expected = f"make prerequisite status differs: {required_path} is {declared_status}"
    assert _g4_reference_error(tmp_path, opposite_reference) == expected


def test_g4_make_prerequisites_fail_closed_without_git_metadata(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("bootstrap-predictor:\n", encoding="utf-8")

    # Fail-closed contract: unavailable Git evidence must RAISE, never read as
    # "absent". A bare `tmp_path` has no repository at all, so HEAD cannot resolve.
    with pytest.raises(RuntimeError, match="source-control evidence is unavailable"):
        _g4_reference_error(
            tmp_path,
            "make:bootstrap-predictor|requires:predictor_model.json|status:absent",
        )


def test_g4_make_prerequisite_ignores_inherited_repository_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intended = tmp_path / "intended"
    redirected = tmp_path / "redirected"
    intended.mkdir()
    redirected.mkdir()
    commit = ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q"]
    for repository in (intended, redirected):
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        (repository / "Makefile").write_text("bootstrap-predictor:\n", encoding="utf-8")
        subprocess.run(["git", "add", "Makefile"], cwd=repository, check=True)
        subprocess.run([*commit, "-m", "seed"], cwd=repository, check=True)
    (redirected / "predictor_model.json").write_text("model", encoding="utf-8")
    subprocess.run(["git", "add", "predictor_model.json"], cwd=redirected, check=True)
    subprocess.run([*commit, "-m", "track"], cwd=redirected, check=True)

    monkeypatch.setenv("GIT_DIR", str(redirected / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(redirected))
    reference = "make:bootstrap-predictor|requires:predictor_model.json|status:absent"
    assert _g4_reference_error(intended, reference) is None
    assert _g4_is_source_controlled(redirected, "predictor_model.json") is True


def test_g4_make_prerequisite_fails_closed_when_head_tree_is_unreadable(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "Makefile").write_text("bootstrap-predictor:\n", encoding="utf-8")
    subprocess.run(["git", "add", "Makefile"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "-m", "seed"],
        cwd=tmp_path,
        check=True,
    )
    tree_oid = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    tree_object = tmp_path / ".git" / "objects" / tree_oid[:2] / tree_oid[2:]
    tree_bytes = tree_object.read_bytes()
    tree_mode = tree_object.stat().st_mode
    tree_object.chmod(tree_mode | stat.S_IWUSR)
    tree_object.unlink()
    reference = "make:bootstrap-predictor|requires:predictor_model.json|status:absent"
    try:
        with pytest.raises(RuntimeError, match="committed tree lookup failed"):
            _g4_reference_error(tmp_path, reference)
    finally:
        tree_object.write_bytes(tree_bytes)
        tree_object.chmod(tree_mode)
    assert _g4_is_source_controlled(tmp_path, "Makefile") is True


def test_g4_make_prerequisite_ignores_commit_replacement_refs(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    commit = ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q"]
    (tmp_path / "Makefile").write_text("bootstrap-predictor:\n", encoding="utf-8")
    subprocess.run(["git", "add", "Makefile"], cwd=tmp_path, check=True)
    subprocess.run([*commit, "-m", "seed"], cwd=tmp_path, check=True)
    (tmp_path / "predictor_model.json").write_text("model", encoding="utf-8")
    subprocess.run(["git", "add", "predictor_model.json"], cwd=tmp_path, check=True)
    subprocess.run([*commit, "-m", "track predictor"], cwd=tmp_path, check=True)

    subprocess.run(["git", "replace", "HEAD", "HEAD^"], cwd=tmp_path, check=True)
    vulnerable = subprocess.run(
        [
            "git",
            "--literal-pathspecs",
            "ls-tree",
            "-z",
            "--full-tree",
            "HEAD",
            "--",
            "predictor_model.json",
        ],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    authoritative = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "--literal-pathspecs",
            "ls-tree",
            "-z",
            "--full-tree",
            "HEAD",
            "--",
            "predictor_model.json",
        ],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    assert vulnerable.stdout == b""
    assert authoritative.stdout

    reference = "make:bootstrap-predictor|requires:predictor_model.json|status:absent"
    assert _g4_reference_error(tmp_path, reference) == (
        "make prerequisite status differs: predictor_model.json is present"
    )


@pytest.mark.parametrize(
    ("reference", "error"),
    (
        ("tests/does_not_exist.py", "file does not exist"),
        ("tests/docs/test_docs_freshness.py::missing_symbol", "symbol does not exist"),
    ),
)
def test_g4_rejects_unmarked_missing_executable_references(reference: str, error: str) -> None:
    with pytest.raises(AssertionError, match=f"unmarked executable reference: {error}"):
        _validate_g4_docs(REPO_ROOT, {"AGENTS.md": f"Evidence: {reference}"})


def test_g4_rejects_syntactically_valid_but_undeclared_id() -> None:
    with pytest.raises(AssertionError, match="stable ID is not declared: FAKE-999"):
        _validate_g4_docs(REPO_ROOT, {"AGENTS.md": "[[ref:id:FAKE-999]]"})


@pytest.mark.parametrize("bound", ("unbounded 1", "1", "1 ???"))
def test_g4_rejects_non_quantified_bound_metadata(bound: str) -> None:
    checklist = _read(REPO_ROOT / "docs/new_lab_acceptance_checklist.md").replace(
        "bound: 1 runtime comparison", f"bound: {bound}", 1
    )
    with pytest.raises(AssertionError, match="G0.1: bound must be a quantified bound expression"):
        _validate_g4_docs(REPO_ROOT, {"docs/new_lab_acceptance_checklist.md": checklist})


def test_g4_allows_software_provable_procedure_declarations() -> None:
    checklist = _read(REPO_ROOT / "docs/new_lab_acceptance_checklist.md").replace(
        "result: PHYSICAL", "result: SOFTWARE-PROVABLE", 1
    )
    _validate_g4_docs(REPO_ROOT, {"docs/new_lab_acceptance_checklist.md": checklist})


def test_g4_fails_closed_when_a_required_document_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _validate_g4_docs(tmp_path)


def test_architecture_snapshot_is_bound_to_index_and_excludes_generated_outputs(
    tmp_path: Path,
    monkeypatch,
):
    import tools.generate_montana_architecture_svgs as generator

    repo = tmp_path / "repo"
    source = repo / "src" / "cryodaq" / "core" / "engine.py"
    generated = repo / "docs" / "refactor" / "architecture-before-all-files.svg"
    source.parent.mkdir(parents=True)
    generated.parent.mkdir(parents=True)
    source.write_bytes(b"indexed\n")
    generated.write_bytes(b"old generated output")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)

    monkeypatch.setattr(generator, "ROOT", repo)
    monkeypatch.setattr(generator, "_TARGET_SNAPSHOT", None)
    frozen = generator.target_snapshot(refresh=True)

    assert frozen.paths == ("src/cryodaq/core/engine.py",)
    assert frozen.read("src/cryodaq/core/engine.py") == b"indexed\n"
    assert frozen.source == "git-index"
    payload = generator.metadata_payload(
        "montana",
        list(frozen.paths),
        0,
        frozen.read,
        frozen,
    )
    assert payload["source_tree_sha"] == frozen.tree_sha
    assert payload["selected_object_manifest_sha256"] == frozen.object_manifest_sha256()

    source.write_bytes(b"unstaged\n")
    assert generator.read_target("src/cryodaq/core/engine.py") == b"indexed\n"
    subprocess.run(["git", "add", str(source)], cwd=repo, check=True)
    assert generator.read_target("src/cryodaq/core/engine.py") == b"indexed\n"

    refreshed = generator.target_snapshot(refresh=True)
    assert refreshed.read("src/cryodaq/core/engine.py") == b"unstaged\n"
    assert refreshed.tree_sha != frozen.tree_sha

    subprocess.run(
        ["git", "rm", "-q", "--cached", "docs/refactor/architecture-before-all-files.svg"],
        cwd=repo,
        check=True,
    )
    expected_tree = subprocess.run(
        ["git", "write-tree"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    canonical = generator.target_snapshot(refresh=True)
    assert canonical.tree_sha == expected_tree


def test_architecture_content_fingerprint_is_checkout_eol_independent():
    import tools.generate_montana_architecture_svgs as generator

    paths = ["docs/example.md"]
    lf = generator.content_fingerprint(paths, lambda _path: b"one\ntwo\n")
    crlf = generator.content_fingerprint(paths, lambda _path: b"one\r\ntwo\r\n")

    assert lf == crlf


def test_architecture_content_fingerprint_keeps_binary_bytes_exact():
    import tools.generate_montana_architecture_svgs as generator

    paths = ["assets/example.bin"]
    crlf = generator.content_fingerprint(paths, lambda _path: b"\x00one\r\ntwo")
    lf = generator.content_fingerprint(paths, lambda _path: b"\x00one\ntwo")

    assert crlf != lf


def _svg_metadata(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    records = [element for element in root if element.tag.endswith("metadata")]
    assert len(records) == 1 and records[0].text
    payload = json.loads(records[0].text)
    assert type(payload) is dict
    return payload


def _svg_nodes(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [
        element.attrib["data-path"]
        for element in root.iter()
        if element.tag.endswith("g") and element.attrib.get("class") == "file-node"
    ]


@cache
def _architecture_inventory() -> tuple[object, tuple[str, ...], dict[str, bytes]]:
    import tools.generate_montana_architecture_svgs as generator

    snapshot = generator.target_snapshot()
    paths = tuple(snapshot.paths)
    return snapshot, paths, {path: snapshot.read(path) for path in paths}


def test_checked_in_montana_architecture_svgs_match_frozen_index_snapshot() -> None:
    """Narrowed to the one surviving architecture graph (manifest SVG decision).

    Previously checked both the exhaustive 1,085-file "all-files" map and the
    legible "important" map. The manifest kept only the latter — the
    all-files map is a provenance artifact, not a document a human or a weak
    model can read, and the two before/after comparison maps are pure
    campaign evidence. Only ``docs/architecture-montana-important.svg``
    (moved out of the campaign-named ``docs/refactor/``) ships in PR-A, so
    this is the only checked-in SVG this test can still verify.
    """
    import tools.generate_montana_architecture_svgs as generator

    snapshot, frozen_paths, contents = _architecture_inventory()
    paths = list(frozen_paths)
    reader = contents.__getitem__
    assert paths
    assert not any(generator._is_generated_output(path) for path in paths)

    important_svg = REPO_ROOT / "docs/architecture-montana-important.svg"
    important = list(generator.IMPORTANT_MONTANA)
    assert _svg_metadata(important_svg) == generator.metadata_payload(
        "montana-important",
        important,
        len(generator.EDGES_MONTANA),
        reader,
        snapshot,
    )
    assert _svg_nodes(important_svg) == important
    generator.verify(important_svg, important, exhaustive=False)


def test_montana_report_inventory_metrics_match_frozen_index_snapshot() -> None:
    """Narrowed to the one surviving architecture graph (manifest SVG decision).

    Previously globbed ``docs/refactor/architecture-*.svg`` and expected all
    four. PR-A ships only ``docs/architecture-montana-important.svg`` (moved
    out of the campaign-named ``docs/refactor/``); the other three never
    existed in this tree.
    """
    import tools.generate_montana_architecture_svgs as generator

    _snapshot, frozen_paths, contents = _architecture_inventory()
    paths = list(frozen_paths)
    source_text = sum(generator.loc(contents[path]) for path in paths)
    production_python = sum(
        generator.loc(contents[path]) for path in paths if path.startswith("src/cryodaq/") and path.endswith(".py")
    )
    test_python = sum(
        generator.loc(contents[path]) for path in paths if path.startswith("tests/") and path.endswith(".py")
    )
    generated = [REPO_ROOT / "docs/architecture-montana-important.svg"]
    assert all(path.is_file() for path in generated)
    delivered_text = source_text + sum(generator.loc(path.read_bytes()) for path in generated)
    report = (REPO_ROOT / "docs/MONTANA_REFACTOR_REPORT.md").read_text(encoding="utf-8")

    expected_rows = (
        f"| Candidate source-inventory text | {source_text:,} lines |",
        f"| Delivered-tree text | {delivered_text:,} lines |",
        f"| Candidate production Python | {production_python:,} lines |",
        f"| Candidate test Python | {test_python:,} lines |",
        f"| Architecture source manifest | {len(paths):,} |",
        f"| Delivered-tree files | {len(paths) + len(generated):,} |",
    )
    for row in expected_rows:
        assert row in report

    runner_lines = generator.loc(contents["scripts/soak_mock_stack_runner.py"])
    soak_lines = generator.loc(contents["scripts/soak_mock_stack.py"])
    assert f"New ~{runner_lines:,}-line runner" in report
    assert f"New/expanded {soak_lines:,} lines" in report


def test_architecture_svg_types_symlinks_and_gitlinks(tmp_path: Path, monkeypatch) -> None:
    import tools.generate_montana_architecture_svgs as generator

    link_oid = "1" * 40
    commit_oid = "2" * 40
    snapshot = generator.GitSnapshot(
        tree_sha="3" * 40,
        source="test:typed-objects",
        entries=(
            generator.GitEntry("links/current", "120000", "blob", link_oid),
            generator.GitEntry("vendor/instrument-sdk", "160000", "commit", commit_oid),
        ),
        blobs={link_oid: b"../targets/current"},
    )
    output = tmp_path / "typed.svg"
    monkeypatch.setattr(generator, "read_base", lambda _path: b"")

    generator.all_files_svg(
        "montana",
        list(snapshot.paths),
        snapshot.read,
        output,
        snapshot,
    )

    root = ET.parse(output).getroot()
    kinds = {
        node.attrib["data-path"]: node.attrib["data-kind"]
        for node in root.iter()
        if node.tag.endswith("g") and node.attrib.get("class") == "file-node"
    }
    assert kinds == {
        "links/current": "symlink",
        "vendor/instrument-sdk": "gitlink",
    }
    assert snapshot.read("links/current") == b"../targets/current"
    assert snapshot.read("vendor/instrument-sdk") == commit_oid.encode("ascii")
    metadata = _svg_metadata(output)
    assert metadata["source_tree_sha"] == snapshot.tree_sha
    assert metadata["selected_object_manifest_sha256"] == snapshot.object_manifest_sha256()


def test_architecture_generation_does_not_replace_outputs_after_render_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import tools.generate_montana_architecture_svgs as generator

    output = tmp_path / "docs" / "refactor"
    output.mkdir(parents=True)
    names = (
        "architecture-before-all-files.svg",
        "architecture-montana-all-files.svg",
        "architecture-before-important.svg",
        "architecture-montana-important.svg",
    )
    for name in names:
        (output / name).write_bytes(b"original")

    base_oid = "a" * 40
    target_oid = "b" * 40
    base = generator.GitSnapshot(
        tree_sha="c" * 40,
        source="test:base",
        entries=(generator.GitEntry("base.py", "100644", "blob", base_oid),),
        blobs={base_oid: b""},
    )
    target = generator.GitSnapshot(
        tree_sha="d" * 40,
        source="test:index",
        entries=(generator.GitEntry("target.py", "100644", "blob", target_oid),),
        blobs={target_oid: b""},
    )
    monkeypatch.setattr(generator, "OUT", output)
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(generator, "base_snapshot", lambda *, refresh=False: base)
    monkeypatch.setattr(generator, "target_snapshot", lambda *, refresh=False: target)
    monkeypatch.setattr(generator, "verify", lambda *_args, **_kwargs: None)

    def render(snapshot, _paths, _reader, destination, _snapshot_info):
        destination.write_bytes(snapshot.encode("ascii"))
        if snapshot == "montana":
            raise RuntimeError("render failed")

    monkeypatch.setattr(generator, "all_files_svg", render)
    monkeypatch.setattr(generator, "important_svg", render)

    with pytest.raises(RuntimeError, match="render failed"):
        generator.generate()
    assert all((output / name).read_bytes() == b"original" for name in names)
