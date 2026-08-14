import re
from collections import Counter
from pathlib import Path

import pytest

CHECKLIST = Path(__file__).parents[2] / "docs" / "new_lab_acceptance_checklist.md"
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
