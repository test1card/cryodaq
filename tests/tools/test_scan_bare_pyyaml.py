import pathlib
import runpy

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCAN = runpy.run_path(str(ROOT / "tools" / "scan_bare_pyyaml.py"))["scan"]


def test_group_a_has_no_bare_pyyaml_loader_calls() -> None:
    findings = SCAN(ROOT / "src" / "cryodaq")
    rendered = "\n".join(f"{path.relative_to(ROOT).as_posix()}:{line}" for path, line in findings)
    assert not findings, f"OC-040 Group A bare PyYAML loader calls remain:\n{rendered}"
