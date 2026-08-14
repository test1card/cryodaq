from __future__ import annotations

from pathlib import Path

import pytest

from tools.oc040_bare_yaml_inventory import find_bare_yaml_calls, find_bare_yaml_calls_in_source

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GROUP_B_ROOTS = (_REPO_ROOT / "src/cryodaq/gui", _REPO_ROOT / "src/cryodaq/agents")


@pytest.mark.parametrize(
    ("source", "expected_function"),
    [
        ("import yaml as _yaml\n_yaml.safe_load('x')\n", "safe_load"),
        ("from yaml import full_load as parse\nparse('x')\n", "full_load"),
        ("import yaml as y\nparse = y.safe_load\nparse('x')\n", "safe_load"),
        ("from yaml import load as parse\nparse('x')\n", "load"),
    ],
)
def test_alias_resolving_inventory_detects_bare_calls(source: str, expected_function: str) -> None:
    findings = find_bare_yaml_calls_in_source(source)
    assert [finding.function for finding in findings] == [expected_function]


def test_alias_resolving_inventory_accepts_explicit_loaders() -> None:
    source = "import yaml as _yaml\n_yaml.load('x', Loader=object)\n"
    assert find_bare_yaml_calls_in_source(source) == []


def test_group_b_has_no_bare_pyyaml_loader_calls() -> None:
    findings = find_bare_yaml_calls(_GROUP_B_ROOTS, _REPO_ROOT)
    locations = "\n".join(f"{finding.location()} {finding.function}" for finding in findings)
    assert not findings, f"OC-040 Group B bare PyYAML loader calls remain:\n{locations}"
