from pathlib import Path
import re


CHECKLIST = Path(__file__).parents[2] / "docs" / "new_lab_acceptance_checklist.md"
GATE_RE = re.compile(r"^G([0-9]+\.[0-9]+):$")


def test_acceptance_checklist_has_exact_gate_set_and_fields():
    lines = CHECKLIST.read_text(encoding="utf-8").splitlines()
    expected = {
        f"{group}.{item}"
        for group, item_count in ((0, 4), (1, 7), (2, 4), (3, 4), (4, 6), (5, 4), (6, 1), (7, 3), (8, 3))
        for item in range(1, item_count + 1)
    }
    gate_indexes = [index for index, line in enumerate(lines) if GATE_RE.match(line)]
    gates = {
        GATE_RE.match(lines[index]).group(1): lines[
            index + 1 : gate_indexes[position + 1] if position + 1 < len(gate_indexes) else len(lines)
        ]
        for position, index in enumerate(gate_indexes)
    }

    assert set(gates) == expected
    assert len(gates) == 36
    for gate_id, block in gates.items():
        for field in ("bound", "abort", "evidence", "result"):
            assert sum(line.startswith(f"  {field}:") for line in block) == 1, gate_id
