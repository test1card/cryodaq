"""Doc-lint: mechanical freshness invariants for the docs-as-product gate (E2).

No LLM, no fuzzy matching — every check below is a plain string/path
comparison against the live tree. Intentionally narrow where a broader
check would produce false positives (see docstrings per test).
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from functools import cache
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_files() -> list[str]:
    """Return Git-tracked repo-relative paths; missing Git evidence is fatal.

    Uses ``-z`` because the line-oriented form applies ``core.quotePath``, which is
    on by default: a tracked path containing a non-ASCII byte comes back as an
    octal-escaped quoted literal such as ``"caf\303\251.md"``.  A caller then opens
    a path that does not exist and, if it swallows the error, skips the file
    silently.  NUL-delimited output is the raw name.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [name for name in out.split("\0") if name]


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def _read(path: Path) -> str:
    """Read required UTF-8 evidence; missing or invalid input must fail."""
    return path.read_text(encoding="utf-8")


def _open_cell_rows(text: str) -> dict[str, tuple[str, ...]]:
    """Parse the canonical open table and reject duplicate row IDs anywhere."""
    assert text.count("| ID | Class |") == 1
    open_text, closed_marker, _closed_text = text.partition("## Closed rows")
    assert closed_marker
    table = open_text.split("| ID | Class |", 1)[1].split("\n", 1)[1].rstrip("\n")
    lines = table.splitlines()
    assert lines and lines[0].startswith("| --- |")

    document_ids = re.findall(r"(?m)^\s*\|\s*(OC-\d{3})\b", text)
    duplicates = sorted(cell_id for cell_id, count in Counter(document_ids).items() if count != 1)
    assert not duplicates, f"open-cell row IDs must be document-wide unique: {duplicates}"

    rows: dict[str, tuple[str, ...]] = {}
    for line in lines[1:]:
        assert line.startswith("| OC-"), line
        fields = tuple(field.strip() for field in line.strip("|").split("|"))
        assert len(fields) == 11, (fields[0], len(fields))
        rows[fields[0]] = fields
    assert set(rows) <= set(document_ids)
    return rows


def _assert_open_cell_gate(rows: dict[str, tuple[str, ...]], cell_id: str) -> None:
    assert cell_id in rows, f"{cell_id} must remain in the canonical open table"
    gate = rows[cell_id][9]
    assert gate.startswith("BLOCKS-DEPLOYMENT — ") and gate.count("BLOCKS-DEPLOYMENT") == 1, (
        f"{cell_id} Gate column must start with the exact BLOCKS-DEPLOYMENT enum",
        gate,
    )


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


def test_open_cells_dispositions_match_recorded_evidence() -> None:
    """Open-cell dispositions must describe the production evidence they cite."""
    rows = {
        fields[1]: row
        for row in _read(REPO_ROOT / "docs" / "OPEN_CELLS.md").splitlines()
        if row.startswith("| OC-")
        if len(fields := [field.strip() for field in row.split("|")]) > 2
    }

    oc_002 = rows["OC-002"]
    oc_017 = rows["OC-017"]
    oc_031 = rows["OC-031"]
    oc_008 = rows["OC-008"]
    failures = []
    if (
        "| OC-002 | C1a/C1b | DEFECT |" not in oc_002
        or "QueryRouter.fetch" not in oc_002.rsplit("|", 3)[-3]
        or "adapter failure is distinct from authoritative empty" not in oc_002.rsplit("|", 3)[-3]
        or "test_router_never_raises_on_adapter_exception" not in oc_002.rsplit("|", 3)[-3]
        or "assistant-producer availability inventory" not in oc_002.rsplit("|", 3)[-3]
        or "NONBLOCKING" not in oc_002.rsplit("|", 3)[-3]
        or "test_router_never_raises_on_adapter_exception" not in oc_002
    ):
        failures.append("OC-002 must be DEFECT and NONBLOCKING")
    if (
        "| OC-017 | C3 | CONTRACT |" not in oc_017
        or oc_017.rsplit("|", 3)[-3].strip()
        != "Terminal-evidence contract for the notification transports. NONBLOCKING."
        or "test_send_message_distinguishes_transport_and_service_confirmation" not in oc_017
    ):
        failures.append("OC-017 must be CONTRACT and NONBLOCKING")
    if "returns `delivered` on HTTP 200 alone" in oc_017:
        failures.append("OC-017 must not claim bare HTTP 200 is delivered")
    if "four tiers" not in oc_017 or "OC-026" not in oc_017:
        failures.append("OC-017 must cite the four-tier repair and OC-026")
    # OC-031 records a concrete guard bypass demonstrated against a green
    # baseline, so by the register's own definition it is a DEFECT; only its
    # scheduling is NONBLOCKING.
    if (
        "| OC-031 | substrate | DEFECT |" not in oc_031
        or "no change to the detected set" not in oc_031
        or "NONBLOCKING" not in oc_031.rsplit("|", 3)[-3]
    ):
        failures.append("OC-031 must be DEFECT and NONBLOCKING")
    # OC-008 may not be closed by recreating the path-and-line-keyed
    # inventory that OC-031 already defeated.
    oc_008_gate = oc_008.rsplit("|", 3)[-3]
    if (
        "normalised semantic site keys" not in oc_008_gate
        or "OC-031 known-bypass regressions" not in oc_008_gate
        or "NONBLOCKING" not in oc_008_gate
    ):
        failures.append("OC-008 closure must require normalised semantic keys and the OC-031 bypass regressions")
    assert not failures, "\n".join(failures)


# A RECORDED measurement, not a re-derivable one: the number of C2 challenges
# whose fingerprint the registry rejects on the declared minimum interpreter.
# RE-MEASURED 2026-08-09 on the OC-023 tree: 108 errors over 134 challenges.
# The previous 110-over-135 pair was taken before this branch registered the
# interlock-binding sites, and BOTH halves had drifted -- the numerator is not
# reusable across a changed sweep any more than the denominator is.
#
# The command, recorded because the last window failed to take this measurement
# at all and wrongly reported the interpreter as absent: `py -3.12` cannot see
# vendor-tagged registrations, so it answers "no suitable runtime" while
# `py -0` lists Astral/CPython3.12.13. Use:
#     uv run --no-project --python 3.12 --with pytest --with pyyaml python -B <probe>
# where the probe imports tests/test_c2_repo_wide_spelling_sweep.py and counts
# `_sites` / `_registry_errors`. Measured the same way: 3.13 and 3.14 give 0.
#
# This guard runs on ONE interpreter and cannot measure another; pinning the
# figure here means the row and the constant move together, and moving them
# requires re-running the sweep on that interpreter.
_RECORDED_MINIMUM_INTERPRETER_ERRORS = 108


@cache
def _declared_minimum_python_version() -> str:
    """Return the floor from `pyproject.toml`'s `requires-python`, e.g. ``3.12``.

    Derived rather than written down, because the caveat this supports is about
    a SPECIFIC declared floor.  If the project raises its minimum, a hardcoded
    "3.12" would keep asserting a sentence about a version nobody supports any
    more -- a stale claim held in place by its own guard.
    """

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        requires = tomllib.load(handle)["project"]["requires-python"]
    match = re.search(r">=\s*(\d+\.\d+)", requires)
    assert match is not None, f"cannot read a minimum version out of requires-python {requires!r}"
    return match.group(1)


def test_open_cells_sweep_counts_are_rederived_from_the_live_sweep() -> None:
    """Counts the register cites about the C2 sweep must come from the sweep.

    Prevention ``REGISTER-DOWNGRADE-ON-UNVERIFIED-SCOPE-301``.  Two register
    errors on 2026-08-05 shared one shape -- a number measured in a narrow scope
    and then asserted in a broad one:

    * OC-008's GUI surface was written as **21**, the count of entries whose
      REASON LABEL is GUI-specific, while the row's gate is about GUI routing
      sites by PATH, of which there are **89**.  A fourfold understatement of
      open work.
    * OC-031 was called substantially closed on a 135/135 exact registry, which
      holds on the CI interpreter and fails 110 of 135 on the minimum the
      project declares supported.

    Prose review did not catch either; both survived into a pushed commit.  So
    the numbers are re-derived here instead of being trusted, which is the
    "parsed registry rather than fragile wording search" the root contract asks
    for.  A drifting count now fails rather than quietly misleading a planner.

    This asserts the counts on the RUNNING interpreter only.  The cross-version
    divergence is a property of the sweep's fingerprint and is tracked in OC-031
    itself -- a guard cannot re-derive a number for an interpreter it is not
    running on, and pretending otherwise would repeat the original error.
    """

    sweep_module = REPO_ROOT / "tests" / "test_c2_repo_wide_spelling_sweep.py"
    if not sweep_module.exists():  # pragma: no cover - the sweep is tracked
        pytest.fail(f"the C2 sweep is missing: {sweep_module}")

    sys.path.insert(0, str(REPO_ROOT / "tests"))
    try:
        sweep = importlib.import_module("test_c2_repo_wide_spelling_sweep")
    finally:
        sys.path.remove(str(REPO_ROOT / "tests"))

    sites = sweep._sites(REPO_ROOT)
    total = len(sites)
    gui_by_path = len([site for site in sites if "/gui/" in site.path.replace("\\", "/")])

    text = _read(REPO_ROOT / "docs" / "OPEN_CELLS.md")
    assert f"{total} detected sites and {total} registrations" in text, (
        f"OPEN_CELLS does not cite the live sweep total of {total} detected sites"
    )
    # Substance, not emphasis: asserting the markdown bold markers would make
    # this guard fail on a reword that changed nothing measurable.
    basis = f"{gui_by_path} of the {total} entries, counted by path under `src/cryodaq/gui/`"
    assert basis in text, f"OPEN_CELLS does not cite the live GUI-by-path count of {gui_by_path} of {total}"

    # EVERY affected row is checked POSITIVELY.  An earlier version of this
    # guard skipped any row that did not already contain the correct figure,
    # so a row reverting to the old unqualified count fell through the
    # `continue` and was never examined -- while the file-wide assertion above
    # stayed satisfied by whichever row was still right.  That is precisely the
    # one-row-away recurrence this prevention exists for, and the guard would
    # have looked enforced while it happened.
    gui_by_reason = len([site for site in sites if site.reason.startswith("GUI ")])
    for row_id in ("OC-008", "OC-031"):
        row = next((line for line in text.splitlines() if line.startswith(f"| {row_id} |")), None)
        assert row is not None, f"{row_id} row is missing from the register"
        assert f"{gui_by_path} of the {total}" in row, (
            f"{row_id} does not cite the GUI-by-path count of {gui_by_path} of {total}"
        )
        assert "counted by path" in row or "by path under" in row, (
            f"{row_id} cites a GUI count without naming the basis it was counted over"
        )
        # The reason-label subset may appear -- it is a true fact -- but only
        # where it is named as the subset it is.
        if f"{gui_by_reason} of the {total}" in row:
            assert "reason" in row.lower(), (
                f"{row_id} cites the {gui_by_reason}-entry subset without naming it a reason-label count"
            )


def test_open_cells_oc031_preserves_its_supported_interpreter_caveat() -> None:
    """The count is only half of what OC-031 must keep saying.

    Prevention ``REGISTER-DOWNGRADE-ON-UNVERIFIED-SCOPE-301``; false-green pair
    ``SWEEP-COUNT-GUARD-INTERPRETER-CAVEAT-FALSE-GREEN-303``.

    The registry's exactness holds on the CI interpreter and rejects 110 of its
    own 135 challenges on the version `pyproject.toml` declares as the floor.
    The sibling count guard asserts only the GUI-by-path wording, so OC-031
    could be edited back to an unqualified "N detected and N registered"
    closure with the interpreter caveat dropped, and that guard would still
    pass -- the same one-row-away hole, one property along.  Codex found it on
    ``bd9f2cf8``.

    This is a separate node rather than more assertions in the sibling because
    it is a separate property, and because the false-green registry binds one
    pair per guard node: folding them together would have made the two escapes
    indistinguishable in the register.
    """

    text = _read(REPO_ROOT / "docs" / "OPEN_CELLS.md")
    oc_031 = next((line for line in text.splitlines() if line.startswith("| OC-031 |")), None)
    assert oc_031 is not None, "OC-031 row is missing from the register"

    minimum = _declared_minimum_python_version()
    assert f"Python {minimum}" in oc_031, (
        f"OC-031 cites the registry's exactness without naming Python {minimum}, the floor "
        f"`pyproject.toml` declares, on which that exactness does not hold"
    )

    # `"errors over" in row` was NOT enough, and Codex demonstrated it on
    # `b0a29cb1`: rewriting 110 to a false 0 kept that substring and the guard
    # kept passing, so the control for "drop the magnitude" established nothing.
    # Parse the numbers instead.
    #
    # And parse them from the SAME CLAUSE as the version label.  Asserting
    # `f"Python {minimum}" in row` anywhere, then matching a magnitude anywhere
    # else, lets the row read "Python 3.12 remains the supported floor, but
    # **Python 3.13 gives 110 errors over 135 challenges**" -- attributing the
    # failure to the interpreter the row itself says AGREES with CI, while both
    # assertions pass. Codex demonstrated that one too, on `6c27f0ee`.
    # Re-derive the MECHANISM rather than trusting the sentence that describes
    # it.  The divergence exists because the challenge fingerprint hashes
    # `ast.dump` text, which is version-dependent.  If that ever stops being
    # true the caveat should be removed -- but only after someone measures it
    # again, which is exactly the step this prevention exists to force.
    sweep_source = _read(REPO_ROOT / "tests" / "test_c2_repo_wide_spelling_sweep.py")
    assert "ast.dump(" in sweep_source, (
        "the C2 sweep no longer fingerprints via `ast.dump`, so the interpreter-binding this guard "
        f"asserts about OC-031 may be stale: re-measure the registry on Python {minimum} and on CI "
        "before editing the caveat out of the row"
    )


def test_open_cells_oc031_binds_the_error_count_to_the_declared_floor() -> None:
    """The magnitude, its denominator, and which interpreter each belongs to.

    Prevention ``REGISTER-DOWNGRADE-ON-UNVERIFIED-SCOPE-301``; false-green pair
    ``SWEEP-COUNT-GUARD-MAGNITUDE-FALSE-GREEN-311``.

    A separate node from the caveat guard because the false-green registry binds
    one pair per node, and because this property has now escaped twice in two
    different ways: first the guard asserted the substring ``errors over``, so
    rewriting 110 to a false 0 kept passing; then it parsed the version and the
    magnitude independently, so the row could attribute the failure to Python
    3.13 -- the interpreter it elsewhere says AGREES with CI -- and still pass.
    Both were found by review, not here.
    """

    text = _read(REPO_ROOT / "docs" / "OPEN_CELLS.md")
    oc_031 = next((line for line in text.splitlines() if line.startswith("| OC-031 |")), None)
    assert oc_031 is not None, "OC-031 row is missing from the register"
    minimum = _declared_minimum_python_version()

    # ONE clause: the declared floor and its own error count.
    match = re.search(
        rf"\*\*Python {re.escape(minimum)}\b[^*]*?(\d+) errors over (\d+) challenges\*\*",
        oc_031,
    )
    assert match is not None, (
        f"OC-031 does not attribute an error count to Python {minimum} in one clause, in the form "
        f"`**Python {minimum} ... <n> errors over <m> challenges**`"
    )
    errors, denominator = int(match.group(1)), int(match.group(2))

    sys.path.insert(0, str(REPO_ROOT / "tests"))
    try:
        sweep = importlib.import_module("test_c2_repo_wide_spelling_sweep")
    finally:
        sys.path.remove(str(REPO_ROOT / "tests"))
    sites = sweep._sites(REPO_ROOT)

    # The DENOMINATOR is re-derivable, so it is derived rather than trusted.
    assert denominator == len(sites), (
        f"OC-031 says the divergence is over {denominator} challenges; the live sweep has {len(sites)}"
    )
    # So is the count on the interpreter this test is RUNNING on. The row claims
    # the registry is exact on CI; that half needs no pinned constant, and
    # asserting it here is what stops the row describing a runtime nobody
    # measured while the guard nods along.
    running_errors = len(sweep._registry_errors(sites))
    assert f"{running_errors} registry errors" in oc_031 or f"gives {running_errors} registry errors" in oc_031, (
        f"OC-031 does not state the live count for the running interpreter "
        f"(Python {sys.version_info.major}.{sys.version_info.minor}), which is {running_errors}"
    )

    # The MAGNITUDE on the declared floor cannot be re-derived here -- this
    # process is not that interpreter, and measuring it by assertion would be
    # claiming a number nobody took, which is the error the whole prevention
    # exists for. It is pinned as a RECORDED measurement instead, so the row and
    # the constant have to move together and moving them means re-running the
    # sweep over there.
    assert 0 < errors <= denominator, f"OC-031 reports {errors} errors over {denominator} challenges"
    assert errors == _RECORDED_MINIMUM_INTERPRETER_ERRORS, (
        f"OC-031 says {errors} errors on Python {minimum}; the recorded measurement is "
        f"{_RECORDED_MINIMUM_INTERPRETER_ERRORS}. If the sweep changed, RE-MEASURE on Python {minimum} "
        "and update both this constant and the row -- do not edit one to match the other."
    )


def test_open_cells_table_and_owner_gates_remain_canonical() -> None:
    """Keep the register contiguous and do not let the general rubric reclassify owner gates."""
    text = _read(REPO_ROOT / "docs" / "OPEN_CELLS.md")
    status = _read(REPO_ROOT / "PROJECT_STATUS.md")
    roadmap = _read(REPO_ROOT / "ROADMAP.md")
    rows = _open_cell_rows(text)
    # The protected set is not a hand-grown list of rows that previously
    # escaped: it is the complete BLOCKS-DEPLOYMENT set, re-derived from the
    # register on every run and pinned to the exact expected inventory so a
    # newly blocking row (or a silently retagged one) is itself a red event.
    expected_blocking = (
        "OC-013",
        "OC-020",
        "OC-023",
        # OC-024 STAYS BLOCKING. The finalisation table now carries declared
        # identity, but the four archive exporters reachable from the same
        # operator-facing panel (csv_export, hdf5_export, parquet_archive,
        # xlsx_export) still emit channel-spelling-only schemas and were not
        # measured. Deregistering the row here would close the deployment gate
        # for that path on the strength of a prose residual -- which is the
        # fix-one-instance-then-close-the-class error this registry exists to
        # catch, and which REGISTER-DOWNGRADE-ON-UNVERIFIED-SCOPE-301 records.
        "OC-024",
        "OC-026",
        # OC-028 STAYS BLOCKING. The owner's A+B behaviour is implemented, but
        # ALARM-NARRATION-SUPPRESSION-WITHOUT-FLOOR-304 and every one of its
        # false-green pairs are status: open with green_evidence: pending, and
        # AGENTS.md:343-350
        # DELIBERATELY NOT A NUMBER. This comment said "all eighteen" while the
        # registry held nineteen, and the same slice's OC-028 row said nineteen
        # -- a reviewed slice contradicting itself. The count moves every round;
        # the registry is the place that knows it.
        # forbids closing a completion disposition while its prevention is open.
        # Partial delivery across a cancellation inside the router is also not
        # preserved; the row names that as an uncovered case rather than implying it
        # is covered.
        "OC-028",
        "OC-030",
        "OC-034",
        "OC-036",
        "OC-037",
        "OC-039",
        # OC-040 registered deliberately. The engine YAML loaders' pre-import
        # ordering was first written NONBLOCKING on the argument that poisoning
        # needs host control of import order; review showed that is wrong -- a
        # dependency or sitecustomize registering a public PyYAML constructor at
        # its own import time is ordinary behaviour, and the result is silent
        # false replacement of safety-bearing alarm configuration. This gate
        # firing on the retag is the gate working: a newly blocking row has to
        # be registered here on purpose, never absorbed quietly.
        "OC-040",
    )
    derived_blocking = tuple(sorted(cell_id for cell_id, fields in rows.items() if "BLOCKS-DEPLOYMENT" in fields[9]))
    assert derived_blocking == expected_blocking, (
        "the register's BLOCKS-DEPLOYMENT inventory drifted from the protected expectation",
        derived_blocking,
    )
    protected = expected_blocking
    owner_ratified = ("OC-020", "OC-036", "OC-037", "OC-039")
    summary = "OC-020/036/037/039 remain **owner-ratified BLOCKS-DEPLOYMENT** rows in this PR."
    assert summary in text

    def assert_derived_owner_gates(candidate_status: str, candidate_roadmap: str) -> None:
        normalized_status = re.sub(r"\s+", " ", candidate_status)
        roadmap_rows = {
            match.group("id"): match.group(0)
            for match in re.finditer(r"(?m)^\| \*\*(?P<id>OC-\d{3})\*\* \|.*$", candidate_roadmap)
        }
        for cell_id in owner_ratified:
            assert f"**{cell_id} — BLOCKS-DEPLOYMENT" in normalized_status
            assert f"| **{cell_id}** | **BLOCKS-DEPLOYMENT" in roadmap_rows[cell_id]

    assert_derived_owner_gates(status, roadmap)

    for cell_id in protected:
        _assert_open_cell_gate(rows, cell_id)

        # Exact mutation that passed the original summary-only guard at 74062e88:
        # preserve its asserted summary while retagging the actual Gate cell.
        mutated_fields = list(rows[cell_id])
        original_row = "| " + " | ".join(mutated_fields) + " |"
        mutated_fields[9] = mutated_fields[9].replace("BLOCKS-DEPLOYMENT", "NONBLOCKING", 1)
        mutated_row = "| " + " | ".join(mutated_fields) + " |"
        mutated = text.replace(original_row, mutated_row, 1)
        assert mutated != text and summary in mutated
        with pytest.raises(AssertionError, match=rf"{cell_id} Gate column"):
            _assert_open_cell_gate(_open_cell_rows(mutated), cell_id)

        for escaped in ("NOT BLOCKS-DEPLOYMENT", "~~BLOCKS-DEPLOYMENT~~"):
            escaped_fields = list(rows[cell_id])
            escaped_fields[9] = escaped_fields[9].replace("BLOCKS-DEPLOYMENT", escaped, 1)
            escaped_row = "| " + " | ".join(escaped_fields) + " |"
            escaped_text = text.replace(original_row, escaped_row, 1)
            assert escaped_text != text
            with pytest.raises(AssertionError, match=rf"{cell_id} Gate column"):
                _assert_open_cell_gate(_open_cell_rows(escaped_text), cell_id)

    duplicate = "| " + " | ".join(rows["OC-020"]) + " |"
    before = text.replace("| ID | Class |", duplicate + "\n| ID | Class |", 1)
    assert before != text
    with pytest.raises(AssertionError, match="document-wide unique"):
        _open_cell_rows(before)

    after = text + "\n" + duplicate + "\n"
    assert after != text
    with pytest.raises(AssertionError, match="document-wide unique"):
        _open_cell_rows(after)

    closed_header = "| ID | Disposition | Surface | Closure evidence |\n| --- | --- | --- | --- |"
    closed = text.replace(closed_header, closed_header + "\n| OC-020 | CLOSED | duplicate | invalid |", 1)
    assert closed != text
    with pytest.raises(AssertionError, match="document-wide unique"):
        _open_cell_rows(closed)

    malformed = text.replace(duplicate, "| OC-020 | malformed |", 1)
    assert malformed != text
    with pytest.raises(AssertionError, match=r"OC-020.*, 2"):
        _open_cell_rows(malformed)

    for cell_id in owner_ratified:
        mutated_status = status.replace(
            f"**{cell_id} — BLOCKS-DEPLOYMENT",
            f"**{cell_id} — NONBLOCKING",
            1,
        )
        assert mutated_status != status
        with pytest.raises(AssertionError):
            assert_derived_owner_gates(mutated_status, roadmap)

        mutated_roadmap = roadmap.replace(
            f"| **{cell_id}** | **BLOCKS-DEPLOYMENT",
            f"| **{cell_id}** | **NONBLOCKING",
            1,
        )
        assert mutated_roadmap != roadmap
        with pytest.raises(AssertionError):
            assert_derived_owner_gates(status, mutated_roadmap)


def test_oc013_physical_off_gate_retag_mutant_is_red() -> None:
    text = _read(REPO_ROOT / "docs" / "OPEN_CELLS.md")
    rows = _open_cell_rows(text)
    _assert_open_cell_gate(rows, "OC-013")
    fields = list(rows["OC-013"])
    original = "| " + " | ".join(fields) + " |"
    fields[9] = fields[9].replace("BLOCKS-DEPLOYMENT", "NONBLOCKING", 1)
    mutated = text.replace(original, "| " + " | ".join(fields) + " |", 1)
    assert mutated != text
    with pytest.raises(AssertionError, match="OC-013 Gate column"):
        _assert_open_cell_gate(_open_cell_rows(mutated), "OC-013")


def test_open_cell_qualification_authority_and_status_remain_current() -> None:
    open_cells = _read(REPO_ROOT / "docs" / "OPEN_CELLS.md")
    status = _read(REPO_ROOT / "PROJECT_STATUS.md")
    roadmap = _read(REPO_ROOT / "ROADMAP.md")
    claim_corrections = _read(REPO_ROOT / "docs" / "CLAIM_CORRECTIONS.md")

    promotion_tree = ast.parse(_read(REPO_ROOT / "build_scripts" / "artifact_promotion.py"))
    promotion_calls = {
        node.func.id
        for node in ast.walk(promotion_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    qualification_tree = ast.parse(_read(REPO_ROOT / "src" / "cryodaq" / "core" / "qualification.py"))
    qualification_functions = {
        node.name for node in ast.walk(qualification_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    promotion_tests = ast.parse(_read(REPO_ROOT / "tests" / "test_artifact_promotion.py"))
    test_count = sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        for node in promotion_tests.body
    )
    assert "verify_artifact_qualification_receipt" in promotion_calls
    assert {"verify_artifact_qualification_receipt", "_signature_valid"} <= qualification_functions
    assert "receipt_binding_digest" not in qualification_functions
    assert test_count == 10

    promotion_blob = subprocess.run(
        ["git", "hash-object", "tests/test_artifact_promotion.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert promotion_blob == "1c1256e5c8274186f61214fa433d31b6053bc62d"

    def assert_current(candidate_cells: str, candidate_status: str, candidate_corrections: str) -> None:
        rows = _open_cell_rows(candidate_cells)
        oc_034 = " | ".join(rows["OC-034"])
        oc_037 = " | ".join(rows["OC-037"])
        normalized_status = re.sub(r"\s+", " ", candidate_status)
        assert "RSA-SHA256" in oc_034 and "RSA-SHA256" in oc_037
        assert "10 tests" in oc_034
        assert "10 passed" not in oc_037
        assert "diagnostic" in oc_037 and "immutable" in oc_037
        assert "workflow provenance" in oc_034 and "direct release upload" in oc_034
        assert "same-ledger duplicate-use refusal" in oc_034
        assert "cross-run replay refusal is not established" in oc_034
        assert "binding_digest` is tamper detection, not a signature" not in oc_034
        _assert_open_cell_gate(rows, "OC-037")
        assert "**OC-037 — BLOCKS-DEPLOYMENT" in normalized_status
        assert "RSA-SHA256" in normalized_status
        assert "workflow provenance" in normalized_status
        assert "direct release upload" in normalized_status
        assert "receipt-producing qualification workflow" in normalized_status
        assert "same-ledger duplicate-use refusal" in normalized_status
        assert "cross-run replay refusal is not established" in normalized_status
        assert "exact current test source contains ten top-level tests" in candidate_corrections
        assert (
            f"Immutable source blob `{promotion_blob}` contains ten top-level `test_*` functions"
            in candidate_corrections
        )
        assert "The current test file contains nine tests" not in candidate_corrections
        assert "reports 9 passed as an unfrozen current-worktree diagnostic" not in candidate_corrections

    assert_current(open_cells, status, claim_corrections)
    assert "OC-034/OC-037 release-promotion and direct-upload restrictions" in roadmap

    unsigned_claim = open_cells.replace(
        "RSA-SHA256 signature verification",
        "binding_digest` is tamper detection, not a signature",
        1,
    )
    assert unsigned_claim != open_cells
    with pytest.raises(AssertionError):
        assert_current(unsigned_claim, status, claim_corrections)

    nine_tests = open_cells.replace("10 tests", "9 tests", 1)
    assert nine_tests != open_cells
    with pytest.raises(AssertionError):
        assert_current(nine_tests, status, claim_corrections)

    omitted_status = status.replace("**OC-037 — BLOCKS-DEPLOYMENT", "**OC-037 omitted", 1)
    assert omitted_status != status
    with pytest.raises(AssertionError):
        assert_current(open_cells, omitted_status, claim_corrections)

    stale_correction = claim_corrections.replace(
        "exact current test source contains ten top-level tests",
        "current test file contains nine tests",
        1,
    )
    assert stale_correction != claim_corrections
    with pytest.raises(AssertionError):
        assert_current(open_cells, status, stale_correction)

    diagnostic_claim = "focused suite: **10 tests (diagnostic source-tree count)**"
    unbound_pass_claim = open_cells.replace(diagnostic_claim, "focused suite: **10 passed**", 1)
    assert unbound_pass_claim != open_cells
    with pytest.raises(AssertionError):
        assert_current(unbound_pass_claim, status, claim_corrections)


def test_current_metrics_uses_frozen_snapshot_against_poisoned_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poisoned inherited index cannot alter metrics from the frozen snapshot."""

    import tools.generate_montana_architecture_svgs as generator

    snapshot = generator.target_snapshot(refresh=True)
    entry = snapshot.entry("docs/OPEN_CELLS.md")
    replacement = snapshot.entry("docs/MONTANA_REFACTOR_REPORT.md")
    svg = b"<svg>\n</svg>\n"
    expected = generator.current_metrics_bytes(snapshot, svg)
    poisoned = tmp_path / "poisoned-index"
    entries = [item for item in snapshot.entries if item.path != entry.path]
    entries.append(replacement.__class__(entry.path, entry.mode, entry.object_type, replacement.oid))
    entries.sort(key=lambda item: item.path)
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(poisoned)
    subprocess.run(("git", "read-tree", "--empty"), cwd=generator.ROOT, env=env, check=True)
    index_info = b"".join(
        item.mode.encode("ascii") + b" " + item.oid.encode("ascii") + b" 0\t" + item.path.encode() + b"\x00"
        for item in entries
    )
    subprocess.run(
        ("git", "update-index", "-z", "--index-info"),
        cwd=generator.ROOT,
        env=env,
        input=index_info,
        check=True,
    )
    monkeypatch.setenv("GIT_INDEX_FILE", str(poisoned))
    assert generator.current_metrics_bytes(snapshot, svg) == expected


def test_baseline_metrics_ignore_replacement_refs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A local `git replace` of the pinned baseline must not move generated metrics.

    Replacement refs can substitute commits, trees, and blobs in supported Git
    state. Generated baseline evidence names the pinned baseline commit, so
    every generator read — revision resolution, tree listing, diff, and direct
    blob reads — must resolve the original objects.
    """

    import tools.generate_montana_architecture_svgs as generator

    clone = tmp_path / "replace-clone"
    subprocess.run(
        ("git", "clone", "--quiet", "--shared", "--no-checkout", ".", str(clone)),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    honest_tree = subprocess.run(
        ("git", "--no-replace-objects", "rev-parse", f"{generator.BASE_SHA}^{{tree}}"),
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert head != generator.BASE_SHA
    subprocess.run(("git", "replace", generator.BASE_SHA, head), cwd=clone, check=True, capture_output=True)
    poisoned_tree = subprocess.run(
        ("git", "rev-parse", f"{generator.BASE_SHA}^{{tree}}"),
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert poisoned_tree != honest_tree

    monkeypatch.setattr(generator, "ROOT", clone)
    snapshot = generator.base_snapshot(refresh=True)
    assert snapshot.tree_sha == honest_tree

    # Direct blob reads are replacement-ref paths too: a replaced baseline
    # blob must still yield its original bytes.
    entry = next(item for item in snapshot.entries if item.kind == "blob")
    original = snapshot.read(entry.path)
    poison_oid = (
        subprocess.run(
            ("git", "hash-object", "-w", "--stdin"),
            cwd=clone,
            input=b"replacement-ref poison\n",
            check=True,
            capture_output=True,
        )
        .stdout.decode("ascii")
        .strip()
    )
    subprocess.run(("git", "replace", entry.oid, poison_oid), cwd=clone, check=True, capture_output=True)
    poisoned_read = subprocess.run(
        ("git", "cat-file", "blob", entry.oid), cwd=clone, check=True, capture_output=True
    ).stdout
    assert poisoned_read == b"replacement-ref poison\n"
    assert generator._cat_blobs((entry.oid,))[entry.oid] == original
    assert generator.base_snapshot(refresh=True).read(entry.path) == original


def test_claim_corrections_changed_python_count_matches_workflow_index() -> None:
    workflow = _read(REPO_ROOT / ".github" / "workflows" / "main.yml")
    corrections = _read(REPO_ROOT / "docs" / "CLAIM_CORRECTIONS.md")

    def assert_current(candidate_workflow: str, candidate_corrections: str) -> None:
        bases = re.findall(r"(?m)^\s*FORMAT_BASE=([0-9a-f]{40})\s*$", candidate_workflow)
        assert len(bases) == 1
        format_base = bases[0]
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", format_base, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ancestry.returncode == 0, ancestry.stderr
        changed = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--name-only",
                "--diff-filter=ACMR",
                format_base,
                "--",
                "*.py",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        assert changed == sorted(set(changed))
        anchor = (
            f"workflow-exact changed-file set in the current candidate index contains **{len(changed):,}** Python paths"
        )
        assert anchor in candidate_corrections

    assert_current(workflow, corrections)

    # The negative control has to mutate the LIVE candidate anchor that
    # ``assert_current`` actually validates.  Matching the first
    # ``contains **N** Python paths`` in the file is not equivalent: this branch
    # also carries the frozen PR7 correction, whose count appears earlier and is
    # deliberately pinned, so mutating it leaves the guard green and the control
    # proves nothing.  The count itself stays un-hardcoded so the control keeps
    # working as the candidate set moves.
    current_anchor = re.search(r"current candidate index contains \*\*[\d,]+\*\* Python paths", corrections)
    assert current_anchor is not None
    stale_count = corrections.replace(
        current_anchor.group(0), "current candidate index contains **669** Python paths", 1
    )
    assert stale_count != corrections
    with pytest.raises(AssertionError):
        assert_current(workflow, stale_count)

    stale_base = workflow.replace(
        "FORMAT_BASE=f5d6434d20dffae62c9f03fbc12f68b03f48351b",
        "FORMAT_BASE=dc2f911b4da7e01325ef4627c21a3f6140d3bc67",
        1,
    )
    assert stale_base != workflow
    with pytest.raises(AssertionError):
        assert_current(stale_base, corrections)

    # Regression for the detached/exported-checkout topology defect: a
    # FORMAT_BASE that is a valid commit but NOT an ancestor of HEAD must fail
    # closed as an AssertionError from the ancestry guard. With the old
    # ``check=True`` form this escaped as a CalledProcessError (which
    # ``pytest.raises(AssertionError)`` cannot catch), so a non-ancestor base in
    # a GitHub-shaped detached checkout turned the guard into an error instead
    # of a clean failure. The dangling commit below is a real child of HEAD, so
    # it is a valid commit that is provably not an ancestor of HEAD, and it
    # touches no ref or working tree.
    non_ancestor_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "cryodaq-test",
        "GIT_AUTHOR_EMAIL": "cryodaq-test@example.com",
        "GIT_COMMITTER_NAME": "cryodaq-test",
        "GIT_COMMITTER_EMAIL": "cryodaq-test@example.com",
    }
    head_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    non_ancestor = subprocess.run(
        ["git", "commit-tree", head_tree, "-p", "HEAD", "-m", "non-ancestor ancestry probe"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=non_ancestor_env,
        check=True,
    ).stdout.strip()
    ancestry_check = subprocess.run(
        ["git", "merge-base", "--is-ancestor", non_ancestor, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ancestry_check.returncode == 1, (non_ancestor, ancestry_check.stderr)
    non_ancestor_workflow = workflow.replace(
        "FORMAT_BASE=f5d6434d20dffae62c9f03fbc12f68b03f48351b",
        f"FORMAT_BASE={non_ancestor}",
        1,
    )
    assert non_ancestor_workflow != workflow
    with pytest.raises(AssertionError):
        assert_current(non_ancestor_workflow, corrections)


def test_open_cell_qualification_replay_scope_matches_production_workflow(tmp_path: Path) -> None:
    from cryodaq.core.qualification import QualificationReceiptError, verify_qualification_receipt
    from tests.qualification_support import (
        VALID_AT,
        qualification_context,
        qualification_receipt_bytes,
    )

    open_cells = _read(REPO_ROOT / "docs" / "OPEN_CELLS.md")
    status = _read(REPO_ROOT / "PROJECT_STATUS.md")
    workflow = _read(REPO_ROOT / ".github" / "workflows" / "qualified-artifact-promotion.yml")
    oc_034 = " | ".join(_open_cell_rows(open_cells)["OC-034"])
    assert "same-ledger duplicate-use refusal" in oc_034
    assert "cross-run replay refusal is not established" in oc_034
    assert "same-ledger duplicate-use refusal" in status
    assert "cross-run replay refusal is not established" in status
    assert '--replay-directory "$RUNNER_TEMP/qualification-replay"' in workflow

    receipt = qualification_receipt_bytes()
    context = qualification_context()
    first_ledger = tmp_path / "workflow-run-1"
    second_ledger = tmp_path / "workflow-run-2"
    verify_qualification_receipt(receipt, expected=context, replay_directory=first_ledger, now_unix_s=VALID_AT)
    with pytest.raises(QualificationReceiptError, match="replay refused"):
        verify_qualification_receipt(receipt, expected=context, replay_directory=first_ledger, now_unix_s=VALID_AT)
    verify_qualification_receipt(receipt, expected=context, replay_directory=second_ledger, now_unix_s=VALID_AT)


def test_open_cell_inventory_and_oc030_locator_match_live_tree() -> None:
    text = _read(REPO_ROOT / "docs" / "OPEN_CELLS.md")
    _snapshot, indexed_paths, contents = _architecture_inventory()
    tracked = list(indexed_paths)

    # Every locator recorded in OC-030's Sites cell is validated against the
    # frozen index, and every live Cyrillic-Te spelling-selection needle under
    # the GUI tree must be recorded: moving, repairing, deleting, or adding a
    # site while the row stays stale turns this guard red. Both the literal
    # "Т" and the escaped "\u0422" spellings are the same detected class.
    oc030_needle = re.compile(r"""startswith\(\s*["'](?:Т|\\u0422)["']\)""")

    def live_oc030_locators(candidate_paths: list[str], candidate_contents: dict[str, bytes]) -> dict[str, list[int]]:
        live: dict[str, list[int]] = {}
        for path in candidate_paths:
            if not (path.startswith("src/cryodaq/gui/") and path.endswith(".py")):
                continue
            blob = candidate_contents.get(path)
            assert blob is not None, f"tracked GUI path has no frozen-index blob: {path}"
            lines = blob.decode("utf-8").splitlines()
            needles = [number for number, line in enumerate(lines, 1) if oc030_needle.search(line)]
            if needles:
                live[path] = needles
        return live

    def recorded_oc030_locators(row_text: str) -> dict[str, list[int]]:
        recorded: dict[str, list[int]] = {}
        for match in re.finditer(r"`(src/cryodaq/gui/[^`:]+?):(\d+)`", row_text):
            recorded.setdefault(match.group(1), []).append(int(match.group(2)))
        return recorded

    def assert_current(
        candidate: str, candidate_paths: list[str], candidate_contents: dict[str, bytes]
    ) -> tuple[int, int]:
        rows = _open_cell_rows(candidate)
        oc_012 = " | ".join(rows["OC-012"])
        oc_030 = " | ".join(rows["OC-030"])
        oc_012_lower = oc_012.lower()
        workflows = sorted(
            path
            for path in candidate_paths
            if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
        )
        governance_modules = sorted(
            path for path in candidate_paths if path.startswith("tests/governance/") and path.endswith(".py")
        )
        reference_blobs = workflows
        referenced_runner_modules: set[str] = set()
        for reference_path in reference_blobs:
            blob = candidate_contents.get(reference_path, b"")
            referenced_runner_modules.update(
                path.decode("utf-8") for path in re.findall(rb"tools/[A-Za-z0-9_/-]+\.py", blob)
            )
            referenced_runner_modules.update(
                path.decode("utf-8").replace(".", "/") + ".py"
                for path in re.findall(rb"tools(?:\.[A-Za-z_][A-Za-z0-9_]*)+", blob)
            )
        required_runner_modules = referenced_runner_modules | {"tools/__init__.py"}
        runner_modules = sorted(required_runner_modules & set(candidate_paths))
        manifest = "".join(path + "\n" for path in workflows + governance_modules + runner_modules).encode("utf-8")
        assert f"all {len(workflows)} tracked workflows" in oc_012_lower
        assert f"all {len(governance_modules)} tracked governance-test modules" in oc_012_lower
        assert f"all {len(runner_modules)} tracked workflow-referenced ci/governance runner modules" in oc_012_lower
        assert set(runner_modules) == required_runner_modules
        # The AGGREGATE, not only its three components.  The row cites an
        # "exact N-path ... inventory" beside the hash, and until this
        # assertion existed that N was checked by nothing: adding a governance
        # module moved all three component counts and the hash, every one of
        # which the guard demanded be updated, while the total silently went
        # stale at 34.  Codex found it on `b0a29cb1`.
        inventory_size = len(workflows) + len(governance_modules) + len(runner_modules)
        assert f"the exact {inventory_size}-path" in oc_012_lower, (
            f"OC-012 does not cite the live inventory size of {inventory_size} paths "
            f"({len(workflows)} workflows + {len(governance_modules)} governance tests "
            f"+ {len(runner_modules)} runner modules)"
        )
        assert "registry/config references were swept" not in oc_012_lower
        assert "sha256:" + hashlib.sha256(manifest).hexdigest() in oc_012
        recorded = recorded_oc030_locators(oc_030)
        assert recorded, "OC-030 must record at least one GUI locator"
        assert recorded == live_oc030_locators(candidate_paths, candidate_contents), (
            "OC-030 locators must match every live Cyrillic-Te spelling-selection site",
            recorded,
            live_oc030_locators(candidate_paths, candidate_contents),
        )
        # The closure gate's prose count must agree with the locator set it
        # summarizes: a stale "all N sites" lets an implementer close the row
        # while leaving a live spelling-inference site unfixed.
        number_words = {
            1: "one",
            2: "two",
            3: "three",
            4: "four",
            5: "five",
            6: "six",
            7: "seven",
            8: "eight",
            9: "nine",
            10: "ten",
            11: "eleven",
            12: "twelve",
        }
        total_locators = sum(len(lines) for lines in recorded.values())
        assert total_locators in number_words
        assert f"at all {number_words[total_locators]} sites" in oc_030.lower(), (
            "OC-030 closure gate must name the exact live locator count",
            total_locators,
        )
        return len(governance_modules), inventory_size

    governance_module_count, inventory_size = assert_current(text, tracked, contents)
    for old, replacement in (
        ("All 6 tracked workflows", "All 4 tracked workflows"),
        (
            f"all {governance_module_count} tracked governance-test modules",
            f"all {governance_module_count - 1} tracked governance-test modules",
        ),
        (f"The exact {inventory_size}-path", f"The exact {inventory_size - 1}-path"),
        (
            "all 10 tracked workflow-referenced CI/governance runner modules",
            "all 9 tracked workflow-referenced CI/governance runner modules",
        ),
        (
            "`src/cryodaq/gui/shell/views/analytics_widgets.py:1632`",
            "`src/cryodaq/gui/shell/views/analytics_widgets.py:1626`",
        ),
        (
            "`src/cryodaq/gui/dashboard/dynamic_sensor_grid.py:167`",
            "`src/cryodaq/gui/dashboard/dynamic_sensor_grid.py:166`",
        ),
        ("`src/cryodaq/gui/dashboard/temp_plot_widget.py:136`", "`src/cryodaq/gui/dashboard/temp_plot_widget.py:135`"),
        ("`src/cryodaq/gui/shell/top_watch_bar.py:1194`", "`src/cryodaq/gui/shell/top_watch_bar.py:1193`"),
        ("at all seven sites", "at all six sites"),
        (
            "`src/cryodaq/gui/shell/overlays/conductivity_panel.py:109`",
            "`src/cryodaq/gui/shell/overlays/conductivity_panel.py:108`",
        ),
    ):
        mutated = text.replace(old, replacement, 1)
        assert mutated != text
        with pytest.raises(AssertionError):
            assert_current(mutated, tracked, contents)

    omitted_locator = text.replace("`src/cryodaq/gui/dashboard/temp_plot_widget.py:136`; ", "", 1)
    assert omitted_locator != text
    with pytest.raises(AssertionError):
        assert_current(omitted_locator, tracked, contents)

    with pytest.raises(AssertionError):
        assert_current(text, [*tracked, ".github/workflows/new-drift.yml"], contents)
    with pytest.raises(AssertionError):
        assert_current(text, [*tracked, "tests/governance/test_new_drift.py"], contents)
    added_reference = dict(contents)
    added_reference[".github/workflows/protected-ci-evidence-gate.yml"] += b"\npython -m tools.ci_new_runner\n"
    added_paths = [*tracked, "tools/ci_new_runner.py"]
    added_reference["tools/ci_new_runner.py"] = b"# referenced runner\n"
    with pytest.raises(AssertionError):
        assert_current(text, added_paths, added_reference)
    with pytest.raises(AssertionError):
        assert_current(text, [path for path in tracked if path != "tools/check_python_compile.py"], contents)
    registry_claim = text.replace(
        "all 10 tracked workflow-referenced CI/governance runner modules were swept",
        (
            "all 10 tracked workflow-referenced CI/governance runner modules were swept, "
            "and the registry/config references were swept"
        ),
        1,
    )
    assert registry_claim != text
    with pytest.raises(AssertionError):
        assert_current(registry_claim, tracked, contents)


def test_p5_report_manifest_claim_remains_pending_until_immutable_freeze() -> None:
    report = _read(REPO_ROOT / "docs" / "MONTANA_REFACTOR_REPORT.md")
    claim_corrections = _read(REPO_ROOT / "docs" / "CLAIM_CORRECTIONS.md")
    open_cells = _read(REPO_ROOT / "docs" / "OPEN_CELLS.md")
    roadmap = _read(REPO_ROOT / "ROADMAP.md")

    def assert_current(candidate_report: str, candidate_corrections: str) -> None:
        report_lower = re.sub(r"\s+", " ", candidate_report.lower().replace(">", " "))
        assert "no immutable p5 frozen-candidate manifest exists" in report_lower
        assert "p5 immutable" in report_lower and "remain pending" in report_lower
        pending_bindings = re.findall(
            r"(?i)no immutable P5 candidate manifest currently binds (?:a|the) final commit/tree",
            candidate_corrections,
        )
        assert len(pending_bindings) == 2
        assert candidate_corrections.lower().count("remains pending until independently verified") >= 2

        binding_verb = re.compile(
            r"(?i)\b(?:"
            r"bind(?:s|ing)?|bound|"
            r"record(?:s|ed|ing)?|"
            r"captur(?:e|es|ed|ing)|"
            r"suppl(?:y|ies|ied|ying)|"
            r"pin(?:s|ned|ning)?|"
            r"establish(?:es|ed|ing)?|"
            r"prov(?:e|es|ed|ing|en)|"
            r"verif(?:y|ies|ied|ying)|"
            r"certif(?:y|ies|ied|ying)"
            r")\b"
        )
        candidate_target = re.compile(r"(?i)\b(?:candidate|final|exported|immutable|P5|frozen[- ]candidate)\b")
        immutable_object = re.compile(r"(?i)\b(?:commit|tree|manifest|sha)\b")
        binding_authority = re.compile(r"(?i)\b(?:external(?:ly)?|exact[- ]?sha|ci|evidence|receipt|run|manifest)\b")
        local_qualifier = re.compile(
            r"(?i)\b(?:"
            r"no|not|never|without|cannot|can't|"
            r"must|will|shall|should|required|requires?|requiring|"
            r"historical|superseded|stale|false|undisclosed|unsupported"
            r")\b"
        )
        leading_historical_or_stale = re.compile(r"(?i)^\s*(?:\*\*)?(?:Historical|Stale)(?:\*\*)?\s*:")
        clause_boundary = re.compile(r"(?i)(?::|[—–]|--|;|\||,\s*(?:and|but|however|yet)\b)")

        def claim_units(text: str) -> list[str]:
            structured = re.sub(
                r"\n(?=(?:\*\*[^*]+:\*\*|#{1,6}\s|[-*]\s))",
                "\n\n",
                text,
            )
            units = []
            for block in re.split(r"\n\s*\n", structured):
                normalized = re.sub(r"\s+", " ", block).strip()
                if not normalized:
                    continue
                normalized = re.sub(r"(?<=[.!?])\s+", "\n", normalized)
                normalized = re.sub(r"\s*[|;]\s*", "\n", normalized)
                normalized = re.sub(
                    r",\s*(?=(?:but|however|yet)\b)|\b(?:however|yet)\s*[:,]",
                    "\n",
                    normalized,
                    flags=re.IGNORECASE,
                )
                units.extend(unit.strip() for unit in normalized.splitlines() if unit.strip())
            return units

        offenders = []
        for unit in claim_units(candidate_report) + claim_units(candidate_corrections):
            for verb in binding_verb.finditer(unit):
                relation = unit[max(0, verb.start() - 160) : verb.end() + 160]
                if not (
                    candidate_target.search(relation)
                    and immutable_object.search(relation)
                    and binding_authority.search(relation)
                ):
                    continue
                qualifier_prefix = unit[max(0, verb.start() - 140) : verb.start()]
                boundaries = list(clause_boundary.finditer(qualifier_prefix))
                if boundaries:
                    qualifier_prefix = qualifier_prefix[boundaries[-1].end() :]
                if leading_historical_or_stale.match(unit):
                    continue
                if not local_qualifier.search(qualifier_prefix):
                    offenders.append(unit)
                    break
        assert not offenders, offenders[:3]
        assert "P5-freeze.json" in roadmap
        assert "They do not supply a P5 frozen candidate" in open_cells

    assert_current(report, claim_corrections)
    restored_report_claim = report.replace(
        (
            "An external candidate manifest is a pending\n"
            "publication prerequisite; no current manifest binds a commit or tree for this\n"
            "report."
        ),
        "The external candidate manifest binds the exact commit and tree.",
        1,
    )
    assert restored_report_claim != report
    with pytest.raises(AssertionError):
        assert_current(restored_report_claim, claim_corrections)

    restored_exact_report_claim = report.replace(
        (
            "An exact-SHA candidate manifest and CI\n"
            "evidence remain pending publication; they are required before generated files\n"
            "can be treated as externally frozen."
        ),
        (
            "The candidate commit is recorded in external exact-SHA CI evidence so generated files remain "
            "byte-stable after they are committed."
        ),
        1,
    )
    assert restored_exact_report_claim != report
    with pytest.raises(AssertionError):
        assert_current(restored_exact_report_claim, claim_corrections)

    restored_corrections_claim, replacements = re.subn(
        r"(?i)no immutable P5 candidate manifest currently binds (?:a|the) final commit/tree[^|\n]*",
        "The external candidate manifest binds the final commit/tree.",
        claim_corrections,
        count=1,
    )
    assert replacements == 1
    assert restored_corrections_claim != claim_corrections
    with pytest.raises(AssertionError):
        assert_current(report, restored_corrections_claim)

    positive_probes = (
        "The external candidate manifest binds the exact commit and tree.",
        "The external candidate manifest captures the exact commit and tree.",
        "The external candidate manifest records the exact commit and tree.",
        "The external candidate manifest supplies the exact commit and tree evidence.",
        "The external candidate manifest proves the exact final commit and tree.",
        "The external candidate manifest verifies the exact final commit and tree.",
        "The external candidate manifest certifies the exact final commit and tree.",
        (
            "No current manifest binds a commit or tree, but the external candidate manifest records the exact "
            "commit and tree."
        ),
        "P5 remains pending; however, the external candidate manifest captures the final commit and tree.",
        "P5 remains open, yet the external candidate manifest supplies the final commit and tree.",
        "This summary is not provisional: the external candidate manifest records the exact final commit and tree.",
        "This summary is not provisional — the external candidate manifest records the exact final commit and tree.",
        "This summary is not provisional, and the external candidate manifest records the exact final commit and tree.",
        "False: the external candidate manifest records the exact final commit and tree.",
        "Superseded: the external candidate manifest records the exact final commit and tree.",
        "Undisclosed: the external candidate manifest records the exact final commit and tree.",
        "Unsupported: the external candidate manifest records the exact final commit and tree.",
        (
            "The candidate commit is not recorded, and the external candidate manifest records the exact final "
            "commit and tree."
        ),
    )
    for probe in positive_probes:
        with pytest.raises(AssertionError):
            assert_current(report + "\n\n" + probe, claim_corrections)

    correction_probe = claim_corrections.replace(
        "so that binding remains pending until independently verified.",
        (
            "so that binding remains pending until independently verified. "
            "The external candidate manifest records the exact final commit and tree."
        ),
        1,
    )
    assert correction_probe != claim_corrections
    with pytest.raises(AssertionError):
        assert_current(report, correction_probe)

    allowed_probes = (
        "The exact candidate commit must be recorded in external CI evidence after commit.",
        "The exact candidate commit will be recorded in external CI evidence after commit.",
        "The exact candidate commit was not recorded in external CI evidence.",
        "Historical: the exact candidate commit was recorded in external CI evidence.",
        "Stale: the exact candidate commit was recorded in external CI evidence.",
        "The exact candidate commit remains pending until independently verified.",
    )
    for probe in allowed_probes:
        assert_current(report + "\n\n" + probe, claim_corrections)


def test_current_metrics_snapshot_binding_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Registered runtime guard for the frozen-snapshot metrics boundary."""

    test_current_metrics_uses_frozen_snapshot_against_poisoned_index(tmp_path, monkeypatch)


def test_oc037_unbound_pass_claim_guard() -> None:
    """Registered runtime guard for OC-037's bound diagnostic evidence."""

    test_open_cell_qualification_authority_and_status_remain_current()


def test_oc012_reference_runner_inventory_guard() -> None:
    """Registered runtime guard for OC-012's derived runner inventory."""

    test_open_cell_inventory_and_oc030_locator_match_live_tree()


def test_p5_pending_manifest_guard() -> None:
    """Registered runtime guard for the pending P5-manifest boundary."""

    test_p5_report_manifest_claim_remains_pending_until_immutable_freeze()


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
            head.stdout.strip(),
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


def test_g4_make_prerequisite_binds_ls_tree_to_verified_head_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    commit = ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q"]
    (tmp_path / "Makefile").write_text("bootstrap-predictor:\n", encoding="utf-8")
    subprocess.run(["git", "add", "Makefile"], cwd=tmp_path, check=True)
    subprocess.run([*commit, "-m", "absent"], cwd=tmp_path, check=True)
    (tmp_path / "predictor_model.json").write_text("model", encoding="utf-8")
    subprocess.run(["git", "add", "predictor_model.json"], cwd=tmp_path, check=True)
    subprocess.run([*commit, "-m", "present"], cwd=tmp_path, check=True)

    original_run = subprocess.run
    verified_commit = original_run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    calls: list[list[str]] = []

    def move_head_after_verification(args, *run_args, **run_kwargs):
        completed = original_run(args, *run_args, **run_kwargs)
        command = list(args)
        calls.append(command)
        if command[-3:] == ["--verify", "--quiet", "HEAD^{commit}"]:
            assert completed.stdout.strip() == verified_commit
            original_run(["git", "reset", "--hard", "HEAD^"], cwd=tmp_path, check=True)
        return completed

    monkeypatch.setattr(subprocess, "run", move_head_after_verification)
    reference = "make:bootstrap-predictor|requires:predictor_model.json|status:absent"
    assert _g4_reference_error(tmp_path, reference) == (
        "make prerequisite status differs: predictor_model.json is present"
    )

    query = next(command for command in calls if "ls-tree" in command)
    assert query[query.index("--full-tree") + 1] == verified_commit
    assert (
        original_run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()
        != verified_commit
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


def test_checked_in_montana_architecture_svgs_match_frozen_index_snapshot(tmp_path: Path) -> None:
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
    rendered = tmp_path / important_svg.name
    generator.important_svg("montana", paths, reader, rendered, snapshot)
    generator.verify(rendered, important, exhaustive=False)
    assert rendered.read_bytes() == generator._git_bytes("show", ":docs/architecture-montana-important.svg")


def test_shipped_architecture_artifact_does_not_claim_removed_companions() -> None:
    # Enumerate every tracked architecture-SVG path, not only the ones this
    # guard already knows about: a companion re-checked-in at any natural
    # location (for example the historical root path
    # `docs/architecture-montana-all-files.svg`) must fail this exact
    # allowlist instead of passing unseen.
    shipped_family = sorted(
        path
        for path in _tracked_files()
        if path.endswith(".svg")
        and (path.startswith("docs/architecture-") or path.startswith("docs/refactor/architecture-"))
    )
    assert shipped_family == ["docs/architecture-montana-important.svg"]

    expected_subtitle = "Selected load-bearing files in the sole shipped architecture map."
    generator = _read(REPO_ROOT / "tools/generate_montana_architecture_svgs.py")
    checked_in = _read(REPO_ROOT / shipped_family[0])
    report = _read(REPO_ROOT / "docs/MONTANA_REFACTOR_REPORT.md")
    assert expected_subtitle in generator
    assert expected_subtitle in checked_in
    for stale_claim in ("exhaustive companion map", "The all-file SVGs"):
        assert stale_claim not in checked_in
        assert stale_claim not in report


def test_montana_report_inventory_metrics_match_frozen_index_snapshot() -> None:
    """Bind one generated metric block and the surviving SVG to one index snapshot."""
    import tools.generate_montana_architecture_svgs as generator

    snapshot, frozen_paths, contents = _architecture_inventory()
    assert frozen_paths and contents
    svg_path = REPO_ROOT / "docs/architecture-montana-important.svg"

    expected = generator.current_metrics_bytes(
        snapshot, generator._git_bytes("show", ":docs/architecture-montana-important.svg")
    )
    assert generator._git_bytes("show", ":docs/current_candidate_metrics.md") == expected

    metrics = expected.decode("utf-8")
    svg_metadata = _svg_metadata(svg_path)
    assert f"| Source snapshot tree | `{snapshot.tree_sha}` |" in metrics
    assert f"| Source snapshot object manifest SHA-256 | `{snapshot.object_manifest_sha256()}` |" in metrics
    assert svg_metadata["source_tree_sha"] == snapshot.tree_sha
    assert svg_metadata["source_tree_file_count"] == len(snapshot.paths)

    report = _read(REPO_ROOT / "docs/MONTANA_REFACTOR_REPORT.md")
    metrics_link = "[generated current-candidate metrics](current_candidate_metrics.md)"
    assert report.count(metrics_link) >= 5
    assert "current_candidate_metrics.md" in report

    # The owner plan must authorize and require both shipped artifacts: the
    # generator writes them from one frozen snapshot, so a plan that
    # regenerates only the SVG leaves the metrics tree hash stale.
    roadmap = _read(REPO_ROOT / "ROADMAP.md")
    p3_amendment = roadmap[roadmap.index("* **P3**") : roadmap.index("* **P4**")]
    assert "docs/architecture-montana-important.svg" in p3_amendment
    assert "docs/current_candidate_metrics.md" in p3_amendment

    # The narrative is no longer a second numeric database. This structural
    # check rejects a newly worded contradictory aggregate instead of listing
    # every prose anchor that happened to exist when the guard was written.
    comma_number = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")
    aggregate_claim = re.compile(
        r"(?i)(?<![\w.])\d(?:[\d,]*\d)?(?:\s+[a-z+/_-]+){0,4}\s+"
        r"(?:files?|paths?|nodes?|lines?|insertions?|deletions?|imports?|additions?|tests?|bytes?)\b"
    )
    # Compact suffix forms (the historical `130k lines` escape named in
    # MONTANA-REPORT-METRIC-FALSE-GREEN-234): the unit suffix is attached to
    # the digits, so the two patterns above cannot see them.
    compact_aggregate_claim = re.compile(
        r"(?i)(?<![\w.])\d+(?:\.\d+)?[kM](?:\s+[a-z+/_-]+){0,4}\s+"
        r"(?:files?|paths?|nodes?|lines?|insertions?|deletions?|imports?|additions?|tests?|bytes?)\b"
    )
    assert not comma_number.search(report)
    assert not aggregate_claim.search(report)
    assert not compact_aggregate_claim.search(report)

    mutant = report + "\nThe current candidate now claims 999999 newly measured source paths.\n"
    assert aggregate_claim.search(mutant)
    for compact_form in ("130k lines", "1M lines"):
        compact_mutant = report + f"\nThe campaign interim count was {compact_form} of source text.\n"
        assert compact_aggregate_claim.search(compact_mutant)


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


def test_architecture_generation_rolls_back_published_outputs_when_a_later_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A failed destination replace must not strand a mixed-snapshot pair.

    Publication is a sequence of single-file replaces; if the metrics
    destination is locked after the SVGs were already replaced, the shipped
    SVG/metrics pair would describe two different index snapshots. Every
    destination published from the failed render must be restored.
    """
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
    metrics_path = tmp_path / "docs" / "current_candidate_metrics.md"

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
    monkeypatch.setattr(generator, "MONTANA_IMPORTANT_SVG", output / "architecture-montana-important.svg")
    monkeypatch.setattr(generator, "CURRENT_METRICS", metrics_path)
    monkeypatch.setattr(generator, "base_snapshot", lambda *, refresh=False: base)
    monkeypatch.setattr(generator, "target_snapshot", lambda *, refresh=False: target)
    monkeypatch.setattr(generator, "verify", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(generator, "current_metrics_bytes", lambda *_args: b"metrics")

    def render(snapshot, _paths, _reader, destination, _snapshot_info):
        destination.write_bytes(snapshot.encode("ascii"))

    monkeypatch.setattr(generator, "all_files_svg", render)
    monkeypatch.setattr(generator, "important_svg", render)

    real_replace = Path.replace

    def failing_replace(self, destination):
        if Path(destination).name == metrics_path.name:
            raise OSError("simulated locked metrics destination")
        return real_replace(self, destination)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="simulated locked metrics destination"):
        generator.generate()
    assert all((output / name).read_bytes() == b"original" for name in names)
    assert not metrics_path.exists()


def test_new_lab_adaptation_uses_instrument_partition_without_health_wiring_claim() -> None:
    text = (REPO_ROOT / "docs" / "new_lab_adaptation.md").read_text(encoding="utf-8")
    section = text.split("## 2. Declare your instruments", 1)[1].split("## 3.", 1)[0]

    assert "::INSTRUMENT_DRIVER_SPECS" in section
    assert "::get_instrument_driver_spec" in section
    assert "no supported production health-node configuration" in section
    assert "::BUILTIN_DRIVER_SPECS" not in section
    assert "::get_driver_spec" not in section


# Mojibake produced by reading UTF-8 bytes as cp1251.  DERIVED, not enumerated: every
# non-ASCII character present in tracked text is at risk, and the image of a NON-Cyrillic
# source is a sequence that genuine Russian does not produce.  Cyrillic sources are
# excluded because their images begin with a Cyrillic letter that Russian text produces
# normally.  U+00BB is excluded for the same reason -- its image is Cyrillic Ve followed
# by a closing guillemet, which occurs genuinely here, including "V = <<B>>" where B is
# the Russian symbol for volts.  Measured: 26 of 26 sequences on the damaged register,
# and zero hits across every tracked file on a clean tree.
_MOJIBAKE_AT_RISK_SOURCES = (
    "\u00a7",
    "\u00ab",
    "\u00ad",
    "\u00b0",
    "\u00b1",
    "\u00b2",
    "\u00b3",
    "\u00b5",
    "\u00b7",
    "\u00b9",
    "\u00bc",
    "\u00bd",
    "\u00d7",
    "\u00e9",
    "\u00f3",
    "\u0301",
    "\u0304",
    "\u0308",
    "\u0394",
    "\u03a3",
    "\u03a9",
    "\u03b1",
    "\u03b2",
    "\u03b5",
    "\u03bc",
    "\u03c3",
    "\u03c4",
    "\u0660",
    "\u0667",
    "\u06f0",
    "\u0966",
    "\u200b",
    "\u2013",
    "\u2014",
    "\u2019",
    "\u201c",
    "\u201d",
    "\u2022",
    "\u2026",
    "\u202e",
    "\u203a",
    "\u2076",
    "\u2079",
    "\u207b",
    "\u2080",
    "\u2081",
    "\u2082",
    "\u2099",
    "\u2116",
    "\u2139",
    "\u2190",
    "\u2191",
    "\u2192",
    "\u2193",
    "\u2194",
    "\u2195",
    "\u21b5",
    "\u21d2",
    "\u21d4",
    "\u2208",
    "\u2212",
    "\u2213",
    "\u221a",
    "\u221e",
    "\u222a",
    "\u2248",
    "\u2260",
    "\u2264",
    "\u2265",
    "\u226a",
    "\u226b",
    "\u2273",
    "\u22ef",
    "\u2500",
    "\u2502",
    "\u250c",
    "\u2510",
    "\u2514",
    "\u251c",
    "\u2524",
    "\u252c",
    "\u2534",
    "\u253c",
    "\u2550",
    "\u2551",
    "\u2554",
    "\u2557",
    "\u255a",
    "\u255d",
    "\u2571",
    "\u2572",
    "\u2588",
    "\u2591",
    "\u2592",
    "\u2593",
    "\u25a0",
    "\u25a1",
    "\u25a3",
    "\u25aa",
    "\u25ac",
    "\u25b2",
    "\u25b6",
    "\u25ba",
    "\u25bc",
    "\u25c0",
    "\u25c6",
    "\u25c7",
    "\u25cb",
    "\u25cf",
    "\u2699",
    "\u26a0",
    "\u26a1",
    "\u2705",
    "\u2713",
    "\u2715",
    "\u2717",
    "\u2726",
    "\u2744",
    "\u274c",
    "\u27e6",
    "\u27e7",
    "\u27f2",
    "\u27fa",
    "\u2b0d",
    "\u2b1c",
    "\u2b24",
    "\ufe0f",
    "\uff0b",
    "\uff0d",
    "\uff0e",
    "\uff10",
    "\uff11",
    "\uff21",
    "\ufffd",
    "\U0001f3db",
    "\U0001f3e0",
    "\U0001f4ca",
    "\U0001f4cb",
    "\U0001f4d3",
    "\U0001f4d6",
    "\U0001f4da",
    "\U0001f4f8",
    "\U0001f514",
    "\U0001f527",
    "\U0001f52c",
    "\U0001f534",
    "\U0001f535",
    "\U0001f6a8",
    "\U0001f7ac",
    "\U0001f7e1",
    "\U0001f916",
    "\U0001f989",
)


def _cp1251_mojibake(source: str) -> str:
    """Return the sequence a character becomes when its UTF-8 bytes are read as cp1251."""
    return source.encode("utf-8").decode("cp1251")


_MOJIBAKE_SIGNATURES = tuple(_cp1251_mojibake(source) for source in _MOJIBAKE_AT_RISK_SOURCES)


def _mojibake_hits(text: str) -> int:
    """Count known mojibake sequences in one decoded document."""
    return sum(text.count(signature) for signature in _MOJIBAKE_SIGNATURES)


# Hand-pinned digest over the whole at-risk source set.  The samples in the control
# below exercise only a handful of signatures, so without this a single deleted source
# would leave every test green -- the vacuous-pass condition, one entry at a time.  Any
# removal, addition or substitution changes this digest.
_MOJIBAKE_SOURCE_DIGEST = "sha256:ae867bafde9155d8f4f8c7f6724f025df77fdc4b7d34f21742482023eacc1fff"


def test_mojibake_source_set_matches_its_pinned_digest() -> None:
    """The at-risk source set may not change without changing this literal.

    Independent by construction: the expected value is written by hand, so weakening
    the production tuple fails here rather than silently shrinking the oracle.
    """
    observed = hashlib.sha256("".join(_MOJIBAKE_AT_RISK_SOURCES).encode("utf-8")).hexdigest()
    assert f"sha256:{observed}" == _MOJIBAKE_SOURCE_DIGEST, (
        "the mojibake at-risk source set changed. If that is intended, re-derive it and "
        "update _MOJIBAKE_SOURCE_DIGEST in the same commit, stating why in the message."
    )


# Hand-pinned digest over the derived MAPPING: every source paired with the exact
# sequence it becomes.  The source digest above cannot see a DERIVATION error -- the
# sources stay identical while the image changes -- and the exercise test below builds
# its samples from `_cp1251_mojibake`, so it would verify a broken value against itself.
# Measured before this anchor existed: returning a dynamically assembled bogus signature
# for a single source left all four guard nodes green, and the real corruption for that
# character escaped the repository sweep.
_MOJIBAKE_MAPPING_DIGEST = "sha256:a013c8446e3dd13bf48760927feb8b792f666b6c8eb6b6cfafffdcc847588993"


def test_mojibake_derivation_matches_its_pinned_mapping() -> None:
    """The source-to-signature mapping may not change without changing this literal.

    Independent of the derivation: the expected value is written by hand, so a wrong
    image fails here instead of certifying itself through the tests that consume it.
    """
    observed = hashlib.sha256(
        "\x1f".join(f"{source}\x1e{_cp1251_mojibake(source)}" for source in _MOJIBAKE_AT_RISK_SOURCES).encode("utf-8")
    ).hexdigest()
    assert f"sha256:{observed}" == _MOJIBAKE_MAPPING_DIGEST, (
        "the cp1251 source-to-signature mapping changed. If that is intended, re-derive it "
        "and update _MOJIBAKE_MAPPING_DIGEST in the same commit, stating why in the message."
    )


def test_every_derived_signature_is_exercised() -> None:
    """Every signature must actually detect, not merely be declared.

    The digest above proves the set is intact; this proves each member works.
    """
    assert len(_MOJIBAKE_SIGNATURES) == len(_MOJIBAKE_AT_RISK_SOURCES)
    assert len(set(_MOJIBAKE_SIGNATURES)) == len(_MOJIBAKE_SIGNATURES), "duplicate signature"
    for source, signature in zip(_MOJIBAKE_AT_RISK_SOURCES, _MOJIBAKE_SIGNATURES, strict=True):
        assert _mojibake_hits(f"before {signature} after") == 1, (
            f"signature derived from U+{ord(source):04X} does not detect its own damage"
        )


def test_mojibake_detector_fires_on_independently_specified_damage() -> None:
    """Positive control bound to LITERALS, never to the production signature set.

    An earlier version of this control looped over ``_MOJIBAKE_SIGNATURES`` and asserted
    ``len(_MOJIBAKE_SIGNATURES)``.  Emptying that tuple therefore satisfied the control
    while the repository sweep below matched nothing -- the oracle shrank with the thing
    it was meant to test.  Every sample and count here is written out by hand so that
    weakening the production set fails this test.
    """
    samples = (
        ("register row \u0432\u0402\u201d end", 1),
        ("print RED \u0432\u0402\u201d tail", 1),
        ("it\u0432\u0402\u2122s", 1),
        ("bullet \u0412\u00b7 item", 1),
        ("ellipsis \u0432\u0402\u00a6 tail", 1),
        ("two \u0432\u0402\u201d and \u0412\u00b7", 2),
    )
    for text, expected in samples:
        assert _mojibake_hits(text) == expected, text

    # Genuine Russian must stay silent.  The third case is the measured reason U+00BB is
    # excluded: a word ending in Ve before a closing guillemet is ordinary text.
    assert _mojibake_hits("\u043a\u0430\u043d\u0430\u043b \u00ab\u04221\u00bb") == 0
    assert _mojibake_hits("plain ASCII \u2014 with real punctuation \u201d\u2026") == 0
    assert _mojibake_hits("V = \u00ab\u0412\u00bb, I = \u00ab\u0410\u00bb") == 0
    assert _mojibake_hits("\u00ab\u0410\u0420\u0425\u0418\u0412 \u041e\u0412\u00bb title") == 0


def test_tracked_text_carries_no_known_mojibake() -> None:
    """No tracked text file may contain a cp1251/UTF-8 mojibake sequence.

    Limits, stated because a guard whose limits are unstated invites the belief that it
    covers more: this catches the cp1251 round-trip only.  It does not catch mojibake
    from a different codepage pair, ASCII-only corruption, replacement characters, damage
    inside binary files, or a corrupted U+00BB, which is excluded above by measurement.
    """
    damaged: dict[str, int] = {}
    for relative in _tracked_files():
        path = REPO_ROOT / relative
        try:
            text = path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, FileNotFoundError, OSError):
            continue  # binary, or a path this platform cannot open
        hits = _mojibake_hits(text)
        if hits:
            damaged[relative] = hits

    assert not damaged, (
        "tracked files carry cp1251/UTF-8 mojibake: "
        f"{sorted(damaged.items())}. Repair with "
        "text.encode('cp1251').decode('utf-8') and verify no ASCII skeleton changed."
    )
