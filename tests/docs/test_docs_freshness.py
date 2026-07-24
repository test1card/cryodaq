"""Doc-lint: mechanical freshness invariants for the docs-as-product gate (E2).

No LLM, no fuzzy matching — every check below is a plain string/path
comparison against the live tree. Intentionally narrow where a broader
check would produce false positives (see docstrings per test).
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path

import pytest

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
    import tools.generate_montana_architecture_svgs as generator

    snapshot, frozen_paths, contents = _architecture_inventory()
    paths = list(frozen_paths)
    reader = contents.__getitem__
    assert paths
    assert not any(generator._is_generated_output(path) for path in paths)

    all_svg = REPO_ROOT / "docs/refactor/architecture-montana-all-files.svg"
    edges = generator.import_edges(paths, reader, snapshot)
    assert _svg_metadata(all_svg) == generator.metadata_payload(
        "montana",
        paths,
        len(edges),
        reader,
        snapshot,
    )
    assert _svg_nodes(all_svg) == paths
    generator.verify(all_svg, paths, exhaustive=True)

    important_svg = REPO_ROOT / "docs/refactor/architecture-montana-important.svg"
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
    generated = sorted((REPO_ROOT / "docs/refactor").glob("architecture-*.svg"))
    assert len(generated) == 4
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
