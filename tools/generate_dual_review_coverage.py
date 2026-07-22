"""Generate the hash-bound Codex + Fable final-review coverage ledger.

The ledger deliberately distinguishes incremental review from final whole-file
approval. A passing review of one commit contributes changed-line coverage, but
it cannot silently approve older Montana edits or unchanged dependency context.
Any content-hash change invalidates coverage from a prior snapshot.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from generate_fable_review_map import _kind, _review_lane

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "scratchpad" / "montana" / "exec" / "dual_review_coverage.md"
BASE_REF = "master"

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_SHA256_ROW_RE = re.compile(r"^\| `([0-9a-f]{64})` \| ([^|]+?) \|$", re.MULTILINE)


def _report_sha256_rows(report: str, start: str, stop: str) -> tuple[tuple[str, str], ...]:
    """Load exact full-file review hashes from a preserved Markdown report."""

    text = (ROOT / report).read_text(encoding="utf-8")
    start_at = text.index(start)
    stop_at = text.index(stop, start_at)
    rows = tuple((path.strip(), digest) for digest, path in _SHA256_ROW_RE.findall(text[start_at:stop_at]))
    if not rows:
        raise RuntimeError(f"No SHA-256 review rows found in {report}")
    return rows


@dataclass(frozen=True, slots=True)
class ReviewRun:
    run_id: str
    reviewers: tuple[str, ...]
    base: str
    head: str
    paths: tuple[str, ...]
    verdict: str
    whole_file: bool
    evidence: str


@dataclass(frozen=True, slots=True)
class WorktreeReviewRun:
    """Review of an uncommitted, hash-frozen worktree slice."""

    run_id: str
    reviewers: tuple[str, ...]
    base: str
    hashes: tuple[tuple[str, str], ...]
    verdict: str
    whole_file_reviewers: tuple[str, ...]
    evidence: str


R07_PATHS = (
    "AGENTS.md",
    "src/cryodaq/core/safety_manager.py",
    "tests/core/test_p1_fixes.py",
    "tests/core/test_safety_operator_snapshot_owner.py",
    "tests/drivers/test_engine_registry_adoption.py",
    "tests/drivers/test_shared_bus_contract.py",
)

R02_PATHS = (
    "src/cryodaq/storage/sqlite_writer.py",
    "src/cryodaq/storage/broker_replay.py",
    "src/cryodaq/reporting/data.py",
    "src/cryodaq/reporting/sections.py",
    "tests/storage/test_fable_r02_hardening.py",
    "tests/storage/test_live_commit_receipts.py",
    "tests/reporting/test_fable_r02_hardening.py",
)

FABLE_BOUNDARY01_WHOLE_PATHS = (
    "config/agent.yaml",
    "src/cryodaq/web/rest_api.py",
    "src/cryodaq/web/server.py",
    "src/cryodaq/agents/assistant_bootstrap.py",
    "src/cryodaq/agents/assistant_main.py",
    "src/cryodaq/agents/assistant/shared/engine_client.py",
    "src/cryodaq/agents/assistant/shared/audit.py",
    "src/cryodaq/agents/assistant/shared/retention.py",
    "src/cryodaq/agents/assistant/live/agent.py",
    "src/cryodaq/agents/assistant/live/output_router.py",
    "src/cryodaq/agents/assistant/query/agent.py",
    "src/cryodaq/agents/assistant/query/router.py",
    "src/cryodaq/agents/assistant/query/adapters/broker_snapshot.py",
    "src/cryodaq/agents/assistant/query/adapters/archive_adapter.py",
    "src/cryodaq/agents/assistant/query/adapters/sqlite_adapter.py",
    "src/cryodaq/agents/assistant/periodic_png.py",
    "src/cryodaq/agents/assistant/periodic_delivery.py",
    "src/cryodaq/agents/assistant/periodic_telegram.py",
    "src/cryodaq/agents/assistant/periodic_runtime.py",
    "src/cryodaq/agents/assistant/periodic_projection.py",
    "src/cryodaq/agents/assistant/report_coordinator.py",
    "src/cryodaq/reporting/__main__.py",
    "src/cryodaq/reporting/periodic_renderer.py",
    "src/cryodaq/reporting/periodic_input.py",
    "src/cryodaq/reporting/data.py",
    "src/cryodaq/reporting/descriptor_projection.py",
)

REVIEW_RUNS = (
    ReviewRun(
        run_id="CODEX+FABLE-R07-20260718",
        reviewers=("codex", "fable"),
        base="49c095bbf8f96ed86ff8581c3e397ca463f75e61",
        head="e38930df6b2d823de55dddbc9224c129c4cc63e3",
        paths=R07_PATHS,
        verdict="reviewed-good",
        whole_file=False,
        evidence="scratchpad/montana/exec/fable_runs/FABLE-R07-20260718.md",
    ),
    ReviewRun(
        run_id="CODEX+FABLE-R02B-20260718",
        reviewers=("codex", "fable"),
        base="e38930df6b2d823de55dddbc9224c129c4cc63e3",
        head="503c8bf",
        paths=R02_PATHS,
        verdict="reviewed-good",
        whole_file=False,
        evidence="scratchpad/montana/exec/fable_runs/FABLE-R02B-20260718.md",
    ),
    ReviewRun(
        run_id="FABLE-BOUNDARY-01-20260719",
        reviewers=("fable",),
        base="1dbaeafd063da3341cf685cffe26a69de4e4a1b0",
        head="503c8bf8d884654256ede4f08a9e44ab7b382242",
        paths=FABLE_BOUNDARY01_WHOLE_PATHS,
        verdict="conditional-pass-with-P3-findings",
        whole_file=True,
        evidence="scratchpad/montana/exec/fable_runs/FABLE-BOUNDARY-01-20260719.md",
    ),
)

WORKTREE_REVIEW_RUNS: tuple[WorktreeReviewRun, ...] = (
    WorktreeReviewRun(
        run_id="FABLE-GUI-01-20260719",
        reviewers=("fable",),
        base="503c8bf8d884654256ede4f08a9e44ab7b382242",
        hashes=_report_sha256_rows(
            "scratchpad/montana/exec/fable_runs/FABLE-GUI-01-20260719.md",
            "### SHA-256 table — files fully read line-by-line (production)",
            "Fully read test file:",
        ),
        verdict="conditional-pass-with-F1-F15",
        whole_file_reviewers=("fable",),
        evidence="scratchpad/montana/exec/fable_runs/FABLE-GUI-01-20260719.md",
    ),
)

ARCHITECTURE_REVIEW_ROWS = (
    (
        "| `FABLE-ARCH-01-20260719` | fable | `e38930df6b2d` plus dirty worktree as read | "
        "CONDITIONAL_PASS | 8.5/10 | no line-level credit; moving-tree limitations | "
        "scratchpad/montana/exec/fable_runs/FABLE-ARCH-01-20260719.md |"
    ),
)

# Independent review can block integration, but cannot substitute for either
# required final reviewer. These findings are hash-bound by their audit report;
# corrections remain blocked until a fresh review run passes the new hashes.
INDEPENDENT_OPEN: dict[str, str] = {
    "src/cryodaq/drivers/transport/usbtmc.py": "R01-QA-P1 cancellation/close overlap",
    "src/cryodaq/drivers/instruments/keithley_2604b.py": (
        "R01-QA-P1 stale disconnected OFF proof; P2 watchdog/nonfinite IV"
    ),
    "src/cryodaq/core/physical_alarms_config.py": ("R01-QA-P1 truncated/nonfinite/invalid-UTF8 fail-safe gap"),
    "src/cryodaq/drivers/registry.py": "R01-QA-P2 private identity-validation bypass",
    "src/cryodaq/drivers/instruments/etalon_multiline.py": ("R01-QA-P2 nonfinite environment values published OK"),
    "src/cryodaq/core/experiment.py": "R06-QA-P0 concurrent ExperimentManager writers",
    "src/cryodaq/engine.py": ("R06/DOCS-P1 timed-out experiment command can commit without downstream reconciliation"),
    "src/cryodaq/storage/archive_reader.py": "R06-QA-P1 hot/cold duplicate authority mismatch",
    "src/cryodaq/storage/cold_rotation.py": "R06-QA-P1 operator-log archive integrity gap",
    "src/cryodaq/reporting/sections.py": "FABLE-BOUNDARY-P3 terminal nonfinite pressure rendered",
    "src/cryodaq/agents/assistant/shared/retention.py": (
        "FABLE-BOUNDARY-P3 symlinked date directory follows external target"
    ),
    "src/cryodaq/gui/shell/experiment_overlay.py": (
        "FABLE-GUI-F1/P2 poll clobbers dirty edits; lifecycle commands fail silently"
    ),
    "src/cryodaq/gui/shell/overlays/keithley_panel.py": (
        "FABLE-GUI-F2/F3/P3 silent emergency failure; unknown maps OFF; stale readouts"
    ),
    "src/cryodaq/gui/dashboard/temp_plot_widget.py": ("FABLE-GUI-F4 automatic first range hides later excursions"),
    "src/cryodaq/gui/shell/main_window_v2.py": "FABLE-GUI-F5/P3 command feedback and worker ownership",
    "src/cryodaq/gui/dashboard/dashboard_view.py": "FABLE-GUI-F5 phase command failure is log-only",
    "src/cryodaq/gui/shell/overlays/alarm_panel.py": "FABLE-GUI-F5 alarm acknowledgement failure is log-only",
    "src/cryodaq/gui/shell/bottom_status_bar.py": ("FABLE-GUI-F6/F7 unknown safety state muted; GUI-thread disk I/O"),
    "src/cryodaq/gui/dashboard/sensor_cell.py": "FABLE-GUI-F8 ambient OK reuses loud safety green",
    "src/cryodaq/gui/state/operator_snapshot_ingress.py": (
        "FABLE-GUI-F9 duplicate revision may flap view disconnected"
    ),
    "src/cryodaq/gui/shell/top_watch_bar.py": "FABLE-GUI-F10 unknown status rank can stop ingestion",
    "src/cryodaq/gui/dashboard/dynamic_sensor_grid.py": ("FABLE-GUI-F10 unknown status rank can abort drained batch"),
    "src/cryodaq/launcher.py": "FABLE-GUI-F11/F14 legacy status colors and launcher-root test gap",
    "src/cryodaq/gui/zmq_client.py": "FABLE-GUI-F12 mixed drain APIs can split one queue",
}


def _git(*args: str, text: bool = True) -> str | bytes:
    options: dict[str, object] = {
        "cwd": ROOT,
        "check": True,
        "capture_output": True,
        "text": text,
    }
    if text:
        # Git emits UTF-8 path/content data; the Russian Windows host locale is
        # cp1251 and cannot decode several tracked Unicode path bytes.
        options.update(encoding="utf-8", errors="strict")
    completed = subprocess.run(["git", "-c", "core.quotepath=false", *args], **options)
    return completed.stdout


def _zpaths(value: bytes) -> set[str]:
    return {item.decode("utf-8", errors="strict").replace("\\", "/") for item in value.split(b"\0") if item}


def _candidate_paths(merge_base: str) -> list[str]:
    tracked_raw = _git("ls-files", "-z", text=False)
    assert isinstance(tracked_raw, bytes)
    paths = _zpaths(tracked_raw)
    changed_raw = _git(
        "diff",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        "-z",
        merge_base,
        "--",
        text=False,
    )
    assert isinstance(changed_raw, bytes)
    # Include paths deleted by Montana: a deleted line must be reviewed too,
    # even though the path no longer appears in the current index.
    paths.update(_zpaths(changed_raw))
    untracked_raw = _git(
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        "src",
        "tests",
        "docs",
        "config",
        "scripts",
        "tools",
        "build_scripts",
        ".github",
        text=False,
    )
    assert isinstance(untracked_raw, bytes)
    paths.update(_zpaths(untracked_raw))
    paths.add("scratchpad/montana/exec/dual_review_coverage.md")
    return sorted(paths)


def _current_bytes(path: str) -> bytes | None:
    candidate = ROOT / path
    if not candidate.is_file():
        return None
    return candidate.read_bytes()


def _sha256(data: bytes | None) -> str:
    return "<deleted>" if data is None else hashlib.sha256(data).hexdigest()


def _text_line_count(data: bytes | None) -> int | None:
    if data is None:
        return 0
    if b"\0" in data:
        return None
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    return len(text.splitlines())


def _parse_diff(args: tuple[str, ...]) -> dict[str, tuple[set[int], int, list[str]]]:
    """Return added/current lines, deleted count, and compact new-line ranges."""

    raw = _git("diff", "--no-ext-diff", "--no-color", "--unified=0", *args)
    assert isinstance(raw, str)
    current: str | None = None
    old_path: str | None = None
    added: dict[str, set[int]] = defaultdict(set)
    deleted: dict[str, int] = defaultdict(int)
    ranges: dict[str, list[str]] = defaultdict(list)
    for line in raw.splitlines():
        if line.startswith("--- "):
            source = line[4:]
            old_path = None if source == "/dev/null" else source.removeprefix("a/")
            continue
        if line.startswith("+++ "):
            target = line[4:]
            current = old_path if target == "/dev/null" else target.removeprefix("b/")
            continue
        if current is None:
            continue
        match = _HUNK_RE.match(line)
        if match is None:
            continue
        old_count = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        deleted[current] += old_count
        if new_count:
            added[current].update(range(new_start, new_start + new_count))
            end = new_start + new_count - 1
            ranges[current].append(str(new_start) if end == new_start else f"{new_start}-{end}")
    return {path: (added[path], deleted[path], ranges[path]) for path in set(added) | set(deleted) | set(ranges)}


def _untracked_paths() -> set[str]:
    raw = _git("ls-files", "--others", "--exclude-standard", "-z", text=False)
    assert isinstance(raw, bytes)
    return _zpaths(raw)


def _head_blob(path: str, ref: str) -> bytes | None:
    completed = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    return completed.stdout if completed.returncode == 0 else None


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> None:
    head = str(_git("rev-parse", "HEAD")).strip()
    branch = str(_git("branch", "--show-current")).strip()
    merge_base = str(_git("merge-base", BASE_REF, "HEAD")).strip()
    paths = _candidate_paths(merge_base)
    untracked = _untracked_paths()

    final_diff = _parse_diff((merge_base, "--"))
    for path in paths:
        if path not in untracked:
            continue
        lines = _text_line_count(_current_bytes(path))
        if lines is not None and lines > 0:
            final_diff[path] = (set(range(1, lines + 1)), 0, [f"1-{lines}"])

    delta_coverage: dict[str, dict[str, set[int]]] = {
        "codex": defaultdict(set),
        "fable": defaultdict(set),
    }
    deleted_coverage: dict[str, dict[str, int]] = {
        "codex": defaultdict(int),
        "fable": defaultdict(int),
    }
    whole_file: dict[str, set[str]] = {"codex": set(), "fable": set()}
    run_rows: list[str] = []
    for run in REVIEW_RUNS:
        run_diff = _parse_diff((run.base, run.head, "--", *run.paths))
        stable = 0
        for path in run.paths:
            current_data = _current_bytes(path)
            reviewed_data = _head_blob(path, run.head)
            if _sha256(current_data) != _sha256(reviewed_data):
                continue
            stable += 1
            added, deleted, _ranges = run_diff.get(path, (set(), 0, []))
            for reviewer in run.reviewers:
                delta_coverage[reviewer][path].update(added)
                if run.base == merge_base and run.head == head:
                    deleted_coverage[reviewer][path] += deleted
                if run.whole_file:
                    whole_file[reviewer].add(path)
        run_rows.append(
            f"| `{run.run_id}` | {', '.join(run.reviewers)} | `{run.base[:12]}..{run.head[:12]}` "
            f"| {run.verdict} | {stable}/{len(run.paths)} hashes current | "
            f"{_escape(run.evidence)} |"
        )

    for run in WORKTREE_REVIEW_RUNS:
        expected_hashes = dict(run.hashes)
        paths_in_run = tuple(expected_hashes)
        run_diff = _parse_diff((run.base, "--", *paths_in_run))
        stable = 0
        for path, expected_hash in run.hashes:
            if _sha256(_current_bytes(path)) != expected_hash:
                continue
            stable += 1
            added, _deleted, _ranges = run_diff.get(path, (set(), 0, []))
            for reviewer in run.reviewers:
                if reviewer in run.whole_file_reviewers:
                    # A stable whole-current-file review covers every current
                    # Montana line, not only the worktree delta over `base`.
                    final_added, _final_deleted, _final_ranges = final_diff.get(path, (set(), 0, []))
                    delta_coverage[reviewer][path].update(final_added)
                    whole_file[reviewer].add(path)
                else:
                    delta_coverage[reviewer][path].update(added)
        run_rows.append(
            f"| `{run.run_id}` | {', '.join(run.reviewers)} | worktree over `{run.base[:12]}` "
            f"| {run.verdict} | {stable}/{len(run.hashes)} hashes current | "
            f"{_escape(run.evidence)} |"
        )

    rows_by_lane: dict[str, list[str]] = defaultdict(list)
    status_counts: dict[str, int] = defaultdict(int)
    total_text_lines = 0
    total_changed_current = 0
    total_deleted = 0
    codex_delta = 0
    fable_delta = 0
    codex_whole = 0
    fable_whole = 0
    fingerprint = hashlib.sha256()

    for path in paths:
        data = _current_bytes(path)
        digest = _sha256(data)
        fingerprint.update(path.encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(digest.encode("ascii"))
        fingerprint.update(b"\0")
        line_count = _text_line_count(data)
        added, deleted, ranges = final_diff.get(path, (set(), 0, []))
        current_changed = len(added)
        codex_changed = len(added & delta_coverage["codex"].get(path, set()))
        fable_changed = len(added & delta_coverage["fable"].get(path, set()))
        codex_full = line_count if line_count is not None and path in whole_file["codex"] else 0
        fable_full = line_count if line_count is not None and path in whole_file["fable"] else 0
        independent = INDEPENDENT_OPEN.get(path, "-")

        if independent != "-":
            status = "reviewed-bad"
        elif (
            line_count is not None
            and path in whole_file["codex"]
            and path in whole_file["fable"]
            and codex_full == line_count
            and fable_full == line_count
            and codex_changed == current_changed
            and fable_changed == current_changed
            and deleted_coverage["codex"].get(path, 0) >= deleted
            and deleted_coverage["fable"].get(path, 0) >= deleted
        ):
            status = "reviewed-good"
        else:
            # Partial coverage is intentionally still unreviewed for the final
            # gate; the numeric columns preserve the progress already earned.
            status = "unreviewed"

        status_counts[status] += 1
        if line_count is not None:
            total_text_lines += line_count
        total_changed_current += current_changed
        total_deleted += deleted
        codex_delta += codex_changed
        fable_delta += fable_changed
        codex_whole += codex_full
        fable_whole += fable_full
        display_lines = "binary" if line_count is None else str(line_count)
        display_ranges = ",".join(ranges) if ranges else "-"
        lane = _review_lane(path)
        rows_by_lane[lane].append(
            f"| `{_escape(path)}` | {_kind(path)} | `{digest}` | {display_lines} | "
            f"+{current_changed}/-{deleted} | `{display_ranges}` | "
            f"{codex_changed}/{current_changed} | {fable_changed}/{current_changed} | "
            f"{codex_full}/{display_lines} | {fable_full}/{display_lines} | "
            f"{_escape(independent)} | `{status}` |"
        )

    generated = datetime.now(UTC).isoformat(timespec="seconds")
    out = [
        "# Dual final-review coverage map",
        "",
        "> This ledger is evidence tracking, not proof by itself. A status is bound "
        "to the exact SHA-256 content shown below. Any file edit invalidates prior coverage.",
        "",
        "## Candidate identity",
        "",
        f"- Generated (UTC): `{generated}`",
        f"- Branch / HEAD: `{branch}` / `{head}`",
        f"- Baseline / merge base: `{BASE_REF}` / `{merge_base}`",
        f"- Candidate content fingerprint: `{fingerprint.hexdigest()}`",
        f"- Inventory: **{len(paths)} files**, **{total_text_lines:,} UTF-8 text lines** plus binary/undecodable files",
        f"- Final diff: **+{total_changed_current:,} current lines / -{total_deleted:,} deleted lines**",
        "",
        "The inventory includes every tracked repository file plus untracked source, "
        "test, documentation, configuration, script, tool, CI, Markdown, TOML, and BAT "
        "candidate. Historical/generated artifacts remain visible rather than being "
        "silently treated as approved.",
        "",
        "## Final gate",
        "",
        "A path becomes `reviewed-good` only when both Codex and Fable reviewed the "
        "entire current text at the displayed hash, both cover every final changed and "
        "deleted line, and no independent finding remains open. Incremental review "
        "earns numeric coverage but remains `unreviewed` until that final whole-file gate.",
        "",
        "| Metric | Codex | Fable | Required |",
        "|---|---:|---:|---:|",
        f"| Final current changed lines | {codex_delta:,} | {fable_delta:,} | {total_changed_current:,} each |",
        f"| Whole current text lines | {codex_whole:,} | {fable_whole:,} | {total_text_lines:,} each |",
        (
            f"| Paths `reviewed-good` | {status_counts['reviewed-good']} | "
            f"{status_counts['reviewed-good']} | {len(paths)} |"
        ),
        f"| Paths `reviewed-bad` | {status_counts['reviewed-bad']} | {status_counts['reviewed-bad']} | 0 |",
        "",
        "## Captured review runs",
        "",
        "| Run | Reviewers | Exact snapshot | Verdict | Current hashes | Evidence |",
        "|---|---|---|---|---:|---|",
        *run_rows,
        "",
        "## Architecture-level reviews",
        "",
        "Architecture reviews challenge system composition and cross-boundary decisions. "
        "They do not grant file or line coverage in the final gate.",
        "",
        "| Run | Reviewer | Observed snapshot | Verdict | Rating | Coverage effect | Evidence |",
        "|---|---|---|---|---:|---|---|",
        *ARCHITECTURE_REVIEW_ROWS,
        "",
        "## Status semantics",
        "",
        "- `unreviewed`: final dual whole-file coverage is incomplete, even if partial counts are nonzero.",
        "- `reviewed-bad`: at least one validated finding is open at this hash.",
        "- `corrected`: reserved for a corrected hash awaiting both re-reviews.",
        "- `reviewed-good`: both required reviewers passed the exact whole file and final diff, with no open finding.",
        "",
    ]
    for lane in sorted(rows_by_lane):
        out.extend(
            [
                f"## Lane `{lane}`",
                "",
                (
                    "| Path | Kind | Candidate SHA-256 | Lines | PR delta | "
                    "Current-line ranges | Codex Δ | Fable Δ | Codex whole | "
                    "Fable whole | Independent finding | Gate |"
                ),
                "|---|---|---|---:|---:|---|---:|---:|---:|---:|---|---|",
                *rows_by_lane[lane],
                "",
            ]
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(out), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
