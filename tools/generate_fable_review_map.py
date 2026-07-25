"""Generate the honest, file-level Fable review coverage ledger.

Broad architecture approval is deliberately kept separate from literal file
review. A path advances only when a captured Fable result names the exact
frozen file or diff and provides an auditable disposition.
"""

# ruff: noqa: E501 - long Markdown table rows remain readable as generated text.

from __future__ import annotations

import hashlib
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "scratchpad" / "montana" / "exec" / "fable_review_map.md"
BASE_REF = "master"

# Include our local audit implementation before it is staged. Generated audit
# output is excluded from the diff fingerprint so tracking the ledger cannot
# make its own fingerprint self-referential.
LOCAL_AUDIT_PATHS = {
    "tools/generate_fable_review_map.py",
    "scratchpad/montana/exec/fable_review_map.md",
}

STATUSES = ("unreviewed", "corrected", "reviewed-good", "reviewed-bad")


@dataclass(frozen=True, slots=True)
class Override:
    status: str
    finding: str
    evidence: str


# Never promote a path merely because a broad architecture pass covered its
# subsystem. Promotion requires an exact, captured disposition for the frozen
# file or diff.
OVERRIDES: dict[str, Override] = {
    "src/cryodaq/launcher.py": Override(
        status="reviewed-bad",
        finding="MON-01",
        evidence=(
            "Preliminary Fable pass flagged indefinite total shutdown retry as "
            "requiring explicit safety sign-off; file changed afterward and awaits "
            "frozen-diff re-review."
        ),
    ),
    "src/cryodaq/agents/assistant/shared/engine_client.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed; allowlist is enforced before transport creation.",
    ),
    "src/cryodaq/agents/assistant/query/agent.py": Override(
        "reviewed-bad",
        "R03A-P3-05",
        "Exact committed HEAD review found an unbounded per-chat rate-bucket registry.",
    ),
    "src/cryodaq/agents/assistant/query/intent_classifier.py": Override(
        "reviewed-bad",
        "R03A-P3-03",
        "Exact committed HEAD review found that the configured classifier timeout is unused.",
    ),
    "src/cryodaq/agents/assistant/query/ru_labels.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed the pure canonical-label re-export.",
    ),
    "src/cryodaq/agents/assistant/query/adapters/alarm_adapter.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed the allowlisted read and fail-closed parsing.",
    ),
    "src/cryodaq/agents/assistant/query/adapters/archive_adapter.py": Override(
        "reviewed-bad",
        "R03A-P3-02",
        "Exact committed HEAD review found an uncontained, unbounded metadata path read.",
    ),
    "src/cryodaq/agents/assistant/query/adapters/broker_snapshot.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed passive cache locking and channel matching.",
    ),
    "src/cryodaq/agents/assistant/query/adapters/cooldown_adapter.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed the single allowlisted read and degradation path.",
    ),
    "src/cryodaq/agents/assistant/query/adapters/experiment_adapter.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed the single allowlisted read.",
    ),
    "src/cryodaq/agents/assistant/query/adapters/sqlite_adapter.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed the bounded engine-mediated history query.",
    ),
    "src/cryodaq/agents/assistant/query/adapters/vacuum_adapter.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed the allowlisted read and bounded reply parsing.",
    ),
    "src/cryodaq/agents/assistant/live/agent.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed text-only dispatch, rate, semaphore and dedup gates.",
    ),
    "src/cryodaq/agents/assistant/live/context_builder.py": Override(
        "reviewed-good",
        "FABLE-R03A-20260717",
        "Exact committed HEAD review passed observational prompt assembly and explicit no-data degradation.",
    ),
    "src/cryodaq/web/rest_api.py": Override(
        "reviewed-bad",
        "R03A-P3-01,R03A-P3-04",
        "Exact committed HEAD review found per-field and chunked-body bound gaps.",
    ),
    "src/cryodaq/web/server.py": Override(
        "reviewed-bad",
        "R03A-P2-01,R03A-P3-06",
        "Exact committed HEAD review found legacy redaction bypass and unfiltered archive scans.",
    ),
}


def _git(*args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=text,
    )
    return completed.stdout


def _lines(value: str | bytes) -> set[str]:
    if not isinstance(value, str):
        value = value.decode("utf-8", errors="strict")
    return {line.strip().replace("\\", "/") for line in value.splitlines() if line.strip()}


def _kind(path: str) -> str:
    if path.startswith("src/"):
        return "production"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith(("scripts/", "tools/", "build_scripts/")):
        return "tooling"
    if path.startswith(".github/"):
        return "ci"
    if path.startswith(("docs/", "scratchpad/")) or path.endswith((".md", ".rst")):
        return "docs"
    if path.startswith(("config/", "plugins/")) or path.endswith((".yaml", ".yml", ".toml", ".json")):
        return "config/packaging"
    return "other"


def _review_lane(path: str) -> str:
    """Assign every changed path to exactly one ordered review lane."""

    value = path.lower()
    name = Path(value).name
    if (
        value
        in {
            "src/cryodaq/engine.py",
            "src/cryodaq/launcher.py",
            "src/cryodaq/instance_lock.py",
            "src/cryodaq/core/safety_manager.py",
            "src/cryodaq/core/scheduler.py",
        }
        or "safety" in value
        or "shutdown" in value
        or "verified_off" in value
        or "verified-off" in value
        or "source_control" in value
        or "source-control" in value
        or name.startswith("test_launcher")
    ):
        return "R00"
    if any(
        marker in value
        for marker in (
            "src/cryodaq/hardware/",
            "src/cryodaq/drivers/",
            "src/cryodaq/instruments/",
            "tests/hardware/",
            "tests/drivers/",
            "tests/instruments/",
            "physical_alarms",
            "instruments.yaml",
        )
    ):
        return "R01"
    if any(
        marker in value
        for marker in (
            "src/cryodaq/storage/",
            "src/cryodaq/reporting/",
            "tests/storage/",
            "tests/reporting/",
            "persistence",
            "archive",
            "replay",
            "receipt",
        )
    ):
        return "R02"
    if value.startswith(
        (
            "src/cryodaq/agents/",
            "src/cryodaq/web/",
            "tests/agents/",
            "tests/web/",
        )
    ):
        return "R03"
    if any(
        marker in value
        for marker in (
            "src/cryodaq/core/",
            "src/cryodaq/ipc/",
            "src/cryodaq/broker",
            "src/cryodaq/transport",
            "periodic_runtime",
            "multiprocess",
            "process_",
            "concurrency",
            "zmq",
        )
    ):
        return "R04"
    if (
        value.startswith(("src/cryodaq/gui/", "tests/gui/", "docs/design-system/"))
        or "operator_snapshot" in value
        or "operator-snapshot" in value
    ):
        return "R05"
    if value.startswith(
        (
            "src/cryodaq/acquisition/",
            "src/cryodaq/analytics/",
            "src/cryodaq/channels/",
            "src/cryodaq/experiments/",
            "tests/acquisition/",
            "tests/analytics/",
            "tests/channels/",
            "tests/experiments/",
        )
    ):
        return "R06"
    if (
        value.startswith((".github/", "build_scripts/", "config/", "packaging/"))
        or name in {"pyproject.toml", "uv.lock", "requirements.txt", "install.bat"}
        or "installer" in value
        or "onedir" in value
    ):
        return "R07"
    if value.startswith(("tests/", "scripts/", "tools/")):
        return "R08"
    if value.startswith(("artifacts/", "outputs/", "scratchpad/")):
        return "R10"
    if value.startswith("docs/") or value.endswith((".md", ".rst")):
        return "R09"
    return "R11"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _tree_fingerprint() -> str:
    exclusions = (
        ":(exclude)scratchpad/montana/exec/fable_review_map.md",
        ":(exclude)scratchpad/montana/exec/fable_runs/**",
    )
    committed = _git(
        "diff",
        "--binary",
        f"{BASE_REF}...HEAD",
        "--",
        ".",
        *exclusions,
        text=False,
    )
    working = _git("diff", "--binary", "HEAD", "--", ".", *exclusions, text=False)
    assert isinstance(committed, bytes) and isinstance(working, bytes)
    return hashlib.sha256(committed + b"\0WORKTREE\0" + working).hexdigest()


def _inventory() -> tuple[list[str], set[str], set[str]]:
    committed = _lines(
        _git(
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            f"{BASE_REF}...HEAD",
        )
    )
    working = _lines(_git("diff", "--name-only", "--diff-filter=ACDMRTUXB", "HEAD"))
    local_audit = {path for path in LOCAL_AUDIT_PATHS if (ROOT / path).exists()}
    runs = ROOT / "scratchpad" / "montana" / "exec" / "fable_runs"
    if runs.exists():
        local_audit.update(file.relative_to(ROOT).as_posix() for file in runs.iterdir() if file.is_file())
    working.update(local_audit)
    return sorted(committed | working), committed, working


def _basis(path: str, committed: set[str], working: set[str]) -> str:
    if path in committed and path in working:
        return "committed + dirty"
    if path in working:
        return "dirty only"
    return "committed"


def main() -> None:
    if set(override.status for override in OVERRIDES.values()) - set(STATUSES):
        raise ValueError("review-map override has an unknown status")

    paths, committed, working = _inventory()
    grouped: dict[str, list[tuple[str, str, str, str, str]]] = defaultdict(list)
    for path in paths:
        override = OVERRIDES.get(path)
        status = override.status if override else "unreviewed"
        finding = override.finding if override else "-"
        evidence = override.evidence if override else "No captured exact-file Fable disposition yet."
        grouped[status].append(
            (
                path,
                _kind(path),
                _review_lane(path),
                _basis(path, committed, working),
                f"{finding}: {evidence}",
            )
        )

    head = str(_git("rev-parse", "HEAD")).strip()
    merge_base = str(_git("merge-base", BASE_REF, "HEAD")).strip()
    branch = str(_git("branch", "--show-current")).strip()
    fingerprint = _tree_fingerprint()
    generated = datetime.now(UTC).isoformat(timespec="seconds")

    counts = {status: len(grouped[status]) for status in STATUSES}
    kinds: dict[str, int] = defaultdict(int)
    lanes: dict[str, int] = defaultdict(int)
    for path in paths:
        kinds[_kind(path)] += 1
        lanes[_review_lane(path)] += 1

    out: list[str] = [
        "# Fable review coverage map",
        "",
        "> Local audit ledger, not product policy and not a substitute for tests or "
        "human safety review. Do not copy raw private-model transcripts here.",
        "",
        "## Frozen-snapshot identity",
        "",
        f"- Generated (UTC): `{generated}`",
        f"- Branch: `{branch}`",
        f"- Baseline ref / merge base: `{BASE_REF}` / `{merge_base}`",
        f"- HEAD: `{head}`",
        f"- Source diff fingerprint (SHA-256): `{fingerprint}`",
        f"- Inventory: **{len(paths)} changed paths** "
        f"({len(committed)} committed, {len(working)} dirty; overlap retained once)",
        "",
        "The fingerprint excludes generated Fable audit output to avoid a "
        "self-reference. Regenerate after every material source edit. A later edit "
        "demotes a path to `unreviewed` unless its exact new evidence is recorded.",
        "",
        "## Status semantics",
        "",
        "| Status | Meaning | Merge consequence |",
        "|---|---|---|",
        "| `unreviewed` | No captured exact-file Fable disposition for this snapshot. Broad architecture or pattern sweeps do not count. | Review it or explicitly retain it as open before merge. |",
        "| `reviewed-bad` | Fable identified an open finding against this path or decision. | Must not merge while the finding is validated and open. |",
        "| `corrected` | Code changed in response to a finding, but Fable has not passed the correction. | Must be re-reviewed. |",
        "| `reviewed-good` | Fable passed the exact frozen file/diff; local verification is still required. | Eligible for the final aggregate gate. |",
        "",
        "State flow: `unreviewed -> reviewed-good | reviewed-bad -> corrected -> reviewed-good | reviewed-bad`.",
        "",
        "## Preliminary architecture review (separate axis)",
        "",
        "The preliminary Fable pass rated Montana as genuine, coherent hardening "
        "rather than a cosmetic refactor. It positively assessed persistence-before-"
        "publication, verified-OFF boundaries, the strict REST write perimeter, "
        "observational assistant allowlists, exact alarm activation identity, sealed "
        "source bindings, bounded report-child ownership, and the eight-job Windows/"
        "Ubuntu CI structure. It reported no P0/P1 in that snapshot and one P2 "
        "(`MON-01`). This is architecture evidence only: Fable explicitly stated that "
        "the entire +168k-line campaign was not literally reviewed line by line in one "
        "session. The captured output was truncated, so `MON-02`..`MON-06` are not "
        "reconstructed from memory.",
        "",
        "## Coverage summary",
        "",
        "| Status | Paths |",
        "|---|---:|",
        *[f"| `{status}` | {counts[status]} |" for status in STATUSES],
        "",
        "| Path kind | Paths |",
        "|---|---:|",
        *[f"| {kind} | {count} |" for kind, count in sorted(kinds.items())],
        "",
        "## Review roadmap",
        "",
        "Lanes are ordered by harm and dependency, not filename. A lane runs only "
        "against an immutable commit or explicitly fingerprinted patch. Production "
        "and tests stay together. Fable findings remain advisory until locally "
        "reproduced and adjudicated.",
        "",
        "| Order | Lane | Paths | Entry condition | Required exit evidence | Current state |",
        "|---:|---|---:|---|---|---|",
        f"| 1 | `R00` Safety, source control, engine and shutdown | {lanes['R00']} | Current authors freeze the diff | Line findings; cancellation/timeout traces; verified-OFF tests; local re-review | Active repair; Fable waits for freeze |",
        f"| 2 | `R03` Assistant observational boundary and web auth | {lanes['R03']} | Stable committed subset at exact HEAD | Exact allowlist/auth source-to-sink review plus focused tests | R03A conditional; corrections active |",
        f"| 3 | `R01` Drivers, instruments and hazardous capabilities | {lanes['R01']} | R00 authority semantics frozen | Capability-escalation/fail-closed review; hardware gates stay open | Queued |",
        f"| 4 | `R02` Persistence, archive, replay and reporting | {lanes['R02']} | Writer/publication ownership frozen | Crash/replay, persistence-before-publication and child-bounds review | Queued |",
        f"| 5 | `R04` Process, IPC, election and concurrency lifecycle | {lanes['R04']} | R00/R02 ownership contracts frozen | Deterministic cancellation/election/process-settlement evidence | Queued |",
        f"| 6 | `R05` GUI, operator truth and design system | {lanes['R05']} | Backend state semantics frozen | Operator scenarios, stale/provenance, accessibility and performance | Queued |",
        f"| 7 | `R06` Acquisition, channels, experiments and analytics | {lanes['R06']} | Descriptor/storage contracts frozen | Identity, time-skew, scientific-validity and degraded-state review | Queued |",
        f"| 8 | `R07` CI, configuration, packaging and installation | {lanes['R07']} | Runtime commands frozen | Windows/WSL/ONEDIR parity and dependency/config drift review | Queued |",
        f"| 9 | `R08` Remaining tests, scripts and audit tooling | {lanes['R08']} | Production lanes reviewed | False-positive/negative, platform-fidelity and evidence audit | Queued |",
        f"| 10 | `R09` Canonical product/operator documentation | {lanes['R09']} | Code/test claims frozen | Claim-to-code traceability and honest open physical gates | Queued |",
        f"| 11 | `R10` Historical/generated evidence and artifacts | {lanes['R10']} | Canonical docs frozen | Retention, provenance, secrecy and non-authority audit | Queued |",
        f"| 12 | `R11` Remaining repository surface | {lanes['R11']} | Prior lanes complete | Explicit classification and aggregate diff review | Queued |",
        "",
        "### Review run queue",
        "",
        "| Run | Lane / snapshot | Scope | State | Output |",
        "|---|---|---|---|---|",
        "| `FABLE-PRELIM-20260717` | Whole architecture / earlier dirty snapshot | Architecture and high-risk pattern sweep; not literal all-file review | Completed, partial transcript | Findings summarized below; exact MON-02..MON-06 text unavailable |",
        "| `FABLE-R03A-ATTEMPT1` | `R03` / invalid expected full SHA | Preflight only | Aborted correctly; zero files reviewed | Superseded `SNAPSHOT_MISMATCH` stub |",
        "| `FABLE-R03A-20260717` | `R03` / committed HEAD only | Assistant query allowlist, web write auth and tests | `CONDITIONAL_PASS`: no P0/P1, one P2 and five P3 IDs across five files | `scratchpad/montana/exec/fable_runs/FABLE-R03A-20260717.md` |",
        "| `FABLE-R00-20260717` | `R00` / future frozen candidate | Safety, engine and launcher shutdown | Blocked only on active authors freezing diff | Planned |",
        "",
        "## Finding registry",
        "",
        "| Finding | State | Affected scope | Current requirement |",
        "|---|---|---|---|",
        "| `MON-01` | Open / `reviewed-bad` | `src/cryodaq/launcher.py` shutdown policy | Freeze implementation, run bounded-shutdown evidence, then Fable re-review. |",
        "| `MON-02`..`MON-06` | Unrecovered text | Unknown; original output was truncated | Do not fabricate. A fresh frozen-diff pass must rediscover or supersede them. |",
        "",
    ]

    titles = {
        "unreviewed": "Unreviewed",
        "corrected": "Corrected; awaiting Fable re-review",
        "reviewed-good": "Reviewed good",
        "reviewed-bad": "Reviewed bad; open findings",
    }
    for status in STATUSES:
        rows = grouped[status]
        out.extend(
            [
                f"## {titles[status]}",
                "",
                f"Paths: **{len(rows)}**",
                "",
                "| Path | Kind | Lane | Snapshot basis | Finding / evidence |",
                "|---|---|---|---|---|",
            ]
        )
        if rows:
            out.extend(
                f"| `{_escape(path)}` | {kind} | `{lane}` | {basis} | {_escape(evidence)} |"
                for path, kind, lane, basis, evidence in rows
            )
        else:
            out.append("| - | - | - | - | No paths currently hold this state. |")
        out.append("")

    out.extend(
        [
            "## Update protocol",
            "",
            "1. Freeze the diff and record HEAD plus the generated fingerprint.",
            "2. Give Fable a bounded path batch and require file-and-line findings.",
            "3. Verify every finding locally; record rejected findings with evidence.",
            "4. Update `OVERRIDES` in `tools/generate_fable_review_map.py` with the captured run ID and result.",
            "5. Regenerate this ledger and never promote paths from an uncaptured summary.",
            "6. After corrections, use `corrected`; only a new exact-diff pass can move a path to `reviewed-good`.",
            "",
        ]
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(out), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
