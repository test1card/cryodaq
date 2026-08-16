import re
from collections import Counter
from pathlib import Path

import pytest

CHECKLIST = Path(__file__).parents[2] / "docs" / "new_lab_acceptance_checklist.md"
READINESS = Path(__file__).parents[2] / "docs" / "evidence_packaging_readiness.md"
GATE_RE = re.compile(r"^G([0-9]+\.[0-9]+):$")


def _parse_procedure_gates(lines):
    opener = "<!-- G4-PROCEDURES"
    assert lines.count(opener) == 1
    comment_start = lines.index(opener)
    comment_end = next(index for index in range(comment_start + 1, len(lines)) if lines[index] == "-->")
    procedure_lines = lines[comment_start + 1 : comment_end]
    gate_indexes = [index for index, line in enumerate(procedure_lines) if GATE_RE.match(line)]
    gate_ids = [GATE_RE.match(procedure_lines[index]).group(1) for index in gate_indexes]
    assert len(gate_ids) == len(set(gate_ids))
    return {
        gate_id: procedure_lines[
            index + 1 : gate_indexes[position + 1] if position + 1 < len(gate_indexes) else len(procedure_lines)
        ]
        for position, (index, gate_id) in enumerate(zip(gate_indexes, gate_ids))
    }


def test_acceptance_checklist_has_exact_gate_set_and_fields():
    lines = CHECKLIST.read_text(encoding="utf-8").splitlines()
    expected = {
        f"{group}.{item}"
        for group, item_count in ((0, 4), (1, 7), (2, 4), (3, 4), (4, 6), (5, 4), (6, 1), (7, 3), (8, 3))
        for item in range(1, item_count + 1)
    }
    gates = _parse_procedure_gates(lines)
    assert set(gates) == expected
    assert len(gates) == 36
    for gate_id, block in gates.items():
        for field in ("bound", "abort", "evidence", "result"):
            assert sum(line.startswith(f"  {field}:") for line in block) == 1, gate_id

    # The readiness document states 24 PHYSICAL gates. Asserting only that each block
    # carries ONE result: field leaves that number unreproducible from anything checked,
    # which is what a reviewer found. Bind the PARTITION instead: the two result values
    # must account for every gate, so a marker cannot be retyped without failing here.
    results = Counter(
        line.split(":", 1)[1].strip() for block in gates.values() for line in block if line.startswith("  result:")
    )
    assert sum(results.values()) == 36, results
    assert results == Counter({"PHYSICAL": 24, "EXTERNALLY_EVIDENCED": 12}), results


def test_procedure_parser_rejects_duplicate_opener_outside_bounded_block():
    lines = CHECKLIST.read_text(encoding="utf-8").splitlines()
    opener_index = lines.index("<!-- G4-PROCEDURES")
    malformed = lines[:opener_index] + ["<!-- G4-PROCEDURES"] + lines[opener_index:]

    with pytest.raises(AssertionError):
        _parse_procedure_gates(malformed)


def test_g71_requires_a_slope_limited_profile_that_covers_the_run():
    from scripts.soak_mock_stack import profile

    lines = CHECKLIST.read_text(encoding="utf-8").splitlines()
    block = "\n".join(_parse_procedure_gates(lines)["7.1"])
    assert "do not select the slope-free short profile for G7.1" in block
    assert "12 h for an intended run from 15 min through 12 h" in block
    assert "observe for that selected profile's full duration" in block

    # Bind the prose selection rule to the production profiles it names, so a
    # changed duration or a removed slope limit fails here rather than leaving
    # the documented acceptance rule stale.
    long12 = profile("12h")
    long72 = profile("72h")
    short = profile("short")
    assert long12.duration_s == 12 * 3600
    assert long72.duration_s == 72 * 3600
    assert long12.rss_slope_limit_bytes_per_hour is not None
    assert long12.descriptor_slope_limit_per_hour is not None
    assert long72.rss_slope_limit_bytes_per_hour is not None
    assert long72.descriptor_slope_limit_per_hour is not None
    assert short.rss_slope_limit_bytes_per_hour is None
    assert short.descriptor_slope_limit_per_hour is None


def test_g71_defines_the_real_stack_capture_and_offline_verdict():
    checklist = CHECKLIST.read_text(encoding="utf-8")
    assert "### G7.1 real-stack resource capture and verdict" in checklist
    assert "Every 5 s from startup through the selected 12 h or 72 h duration" in checklist
    assert "the mock-stack evidence validator is not evidence for this real-instrument gate" in checklist


def test_threshold_coverage_agrees_that_only_g31_remains_open():
    readiness = READINESS.read_text(encoding="utf-8")
    assert "G3.1 is the only remaining gate without a measurable decision threshold" in readiness
    assert "G3.1 and G7.1 lack measurable decision thresholds" not in readiness
