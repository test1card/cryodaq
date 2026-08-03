"""Behavioral acceptance: the shipped imaginary-lab example validates end to end."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from cryodaq.drivers.registry import BUILTIN_DRIVER_SPECS, DriverAuthority, DriverCapability
from cryodaq.lab_profile import QuestionKind, load_lab_profile

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = REPO_ROOT / "docs" / "examples" / "lab_profile.imaginary_lab.yaml"

EXPECTED_TYPES = ("lakeshore_218s", "thyracont_vsp63d", "etalon_multiline")
EXPECTED_NAMES = ("LS218_1", "VSP63_1", "ML_1")


def test_shipped_imaginary_example_loads() -> None:
    profile = load_lab_profile(EXAMPLE_PATH)
    assert profile.lab_id == "imaginary-asc-lab"
    assert profile.display_name == "Imaginary ASC Lab"
    assert tuple(instrument.type_name for instrument in profile.instruments) == EXPECTED_TYPES
    assert tuple(instrument.name for instrument in profile.instruments) == EXPECTED_NAMES


def test_derived_capabilities_match_independent_registry_union() -> None:
    profile = load_lab_profile(EXAMPLE_PATH)
    expected_capabilities: set[DriverCapability] = set()
    expected_trust: set[DriverAuthority] = set()
    for type_name in EXPECTED_TYPES:
        spec = BUILTIN_DRIVER_SPECS[type_name]
        expected_capabilities |= spec.capabilities
        expected_trust.add(spec.authority)
    assert profile.capabilities.instrument_types == EXPECTED_TYPES
    assert profile.capabilities.capabilities == expected_capabilities
    assert profile.capabilities.trust_classes == expected_trust


def test_every_derived_trust_class_is_passive() -> None:
    profile = load_lab_profile(EXAMPLE_PATH)
    passive = {DriverAuthority.PASSIVE_MEASUREMENT, DriverAuthority.PASSIVE_EXTENSION}
    assert profile.capabilities.trust_classes <= passive
    assert DriverAuthority.REVIEWED_SOURCE not in profile.capabilities.trust_classes


def test_profile_grants_no_authority() -> None:
    profile = load_lab_profile(EXAMPLE_PATH)
    assert profile.capabilities.actuation_supported is False
    assert profile.capabilities.grants_control_authority is False
    assert profile.grants_control_authority is False


def test_questions_are_open_and_typed() -> None:
    profile = load_lab_profile(EXAMPLE_PATH)
    assert profile.is_fully_answered is False
    assert len(profile.questions) == 2
    for question in profile.questions:
        assert type(question.kind) is QuestionKind


def test_cli_validates_the_shipped_example() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "cryodaq.lab_profile", str(EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "lab_id: imaginary-asc-lab" in completed.stdout
    assert "actuation_supported: false" in completed.stdout
    assert "safety_critical_roster" in completed.stdout


def test_cli_prints_unicode_identities_under_a_legacy_stdout_encoding(tmp_path) -> None:
    profile_path = tmp_path / "cyrillic.yaml"
    profile_path.write_text(
        "schema_version: 1\n"
        "lab:\n"
        "  lab_id: лаборатория\n"
        "  display_name: Криогенная лаборатория\n"
        "instruments:\n"
        "  - type: lakeshore_218s\n"
        "    name: LS1\n"
        "questions: []\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONIOENCODING"] = "cp1252"
    completed = subprocess.run(
        [sys.executable, "-m", "cryodaq.lab_profile", str(profile_path)],
        capture_output=True,
        text=False,
        env=env,
        cwd=REPO_ROOT,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
