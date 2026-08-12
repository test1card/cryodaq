"""Every forbidden mutation of a lab profile is rejected by construction."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from cryodaq.drivers.registry import DriverAuthority, DriverCapability
from cryodaq.lab_profile import (
    ActuationBoundaryError,
    LabCapabilities,
    LabProfileError,
    ProfileInstrument,
    load_lab_profile,
    parse_lab_profile,
)


def _base() -> str:
    return """\
schema_version: 1
lab:
  lab_id: hostile-lab
  display_name: Hostile Lab
instruments:
  - type: lakeshore_218s
    name: LS1
questions: []
"""


def _with_root_key(key: str) -> str:
    return f"{_base()}{key}: {{}}\n"


def _with_schema_version(value: str) -> str:
    return _base().replace("schema_version: 1", f"schema_version: {value}")


def _with_instrument(entry: str) -> str:
    return _base().replace("  - type: lakeshore_218s\n    name: LS1\n", entry)


def _with_questions(block: str) -> str:
    return _base().replace("questions: []", block)


def _unknown_driver_text() -> str:
    return _base().replace("type: lakeshore_218s", "type: not_a_driver")


def _keithley_text() -> str:
    return _base().replace("type: lakeshore_218s", "type: keithley_2604b")


def _health_node_text() -> str:
    return _base().replace("type: lakeshore_218s", "type: deterministic_health_node")


def _alias_text() -> str:
    return (
        _base()
        .replace("lab_id: hostile-lab", "lab_id: &lid hostile-lab")
        .replace("display_name: Hostile Lab", "display_name: *lid")
    )


def _duplicate_key_text() -> str:
    return _base().replace("lab_id: hostile-lab", "lab_id: hostile-lab\n  lab_id: hostile-lab")


def _unknown_question_kind_text() -> str:
    return _with_questions("questions:\n  - kind: made_up_kind\n    subject: s\n    summary: s\n")


def _question_missing_summary_text() -> str:
    return _with_questions("questions:\n  - kind: class_a_thresholds\n    subject: s\n")


def _spaced_name_text() -> str:
    return _base().replace("name: LS1", 'name: "LS 1"')


def _path_name_text() -> str:
    return _base().replace("name: LS1", "name: ../etc")


def _empty_instruments_text() -> str:
    return _base().replace("  - type: lakeshore_218s\n    name: LS1\n", "")


def _duplicate_names_text() -> str:
    return _with_instrument("  - type: lakeshore_218s\n    name: LS1\n  - type: thyracont_vsp63d\n    name: LS1\n")


def _instrument_actuation_key_text() -> str:
    return _with_instrument("  - type: lakeshore_218s\n    name: LS1\n    actuation: {}\n")


HOSTILE_TEXTS: tuple[str, ...] = (
    _unknown_driver_text(),
    _keithley_text(),
    _with_root_key("safety"),
    _with_root_key("thresholds"),
    _with_root_key("interlocks"),
    _with_root_key("overrides"),
    _instrument_actuation_key_text(),
    _with_schema_version("2"),
    _with_schema_version("true"),
    _alias_text(),
    _duplicate_key_text(),
    _unknown_question_kind_text(),
    _question_missing_summary_text(),
    _spaced_name_text(),
    _path_name_text(),
    _empty_instruments_text(),
    _duplicate_names_text(),
)


def test_unknown_driver_type_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="closed allowlist"):
        parse_lab_profile(_unknown_driver_text())


def test_source_authority_instrument_is_rejected() -> None:
    with pytest.raises(ActuationBoundaryError, match="hazardous actuator"):
        parse_lab_profile(_keithley_text())


def test_health_telemetry_metadata_is_not_a_direct_profile_instrument() -> None:
    with pytest.raises(LabProfileError, match="instrument"):
        ProfileInstrument("deterministic_health_node", "compressor.primary")


def test_health_telemetry_yaml_is_not_a_profile_instrument() -> None:
    with pytest.raises(LabProfileError, match="instrument"):
        parse_lab_profile(_health_node_text())


def test_health_telemetry_cli_rejects_profile_with_exit_two(tmp_path) -> None:
    profile_path = tmp_path / "health-node.yaml"
    profile_path.write_text(_health_node_text(), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "cryodaq.lab_profile", str(profile_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 2, completed.stdout
    assert "LAB PROFILE ERROR:" in completed.stderr


@pytest.mark.parametrize("surface", ["safety", "thresholds", "interlocks", "overrides"])
def test_incumbent_root_keys_are_rejected(surface: str) -> None:
    with pytest.raises(LabProfileError, match="deliberately not representable"):
        parse_lab_profile(_with_root_key(surface))


def test_instrument_actuation_key_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="deliberately not representable"):
        parse_lab_profile(_instrument_actuation_key_text())


def test_schema_version_two_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="schema_version must be the integer 1"):
        parse_lab_profile(_with_schema_version("2"))


def test_schema_version_bool_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="schema_version must be the integer 1"):
        parse_lab_profile(_with_schema_version("true"))


def test_yaml_alias_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="aliases are not allowed"):
        parse_lab_profile(_alias_text())


def test_duplicate_key_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="duplicate key"):
        parse_lab_profile(_duplicate_key_text())


def test_file_over_byte_ceiling_is_rejected(tmp_path) -> None:
    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b"# " + b"x" * (70 * 1024))
    with pytest.raises(LabProfileError, match="bounded file grammar"):
        load_lab_profile(oversized)


def test_non_regular_file_is_rejected(tmp_path) -> None:
    with pytest.raises(LabProfileError, match="regular file"):
        load_lab_profile(tmp_path)


def test_unknown_question_kind_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="unknown question kind"):
        parse_lab_profile(_unknown_question_kind_text())


def test_question_missing_summary_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="missing required keys"):
        parse_lab_profile(_question_missing_summary_text())


def test_instrument_name_with_internal_space_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="whitespace"):
        parse_lab_profile(_spaced_name_text())


def test_instrument_name_with_path_syntax_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="path syntax"):
        parse_lab_profile(_path_name_text())


def test_empty_instruments_list_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="non-empty"):
        parse_lab_profile(_empty_instruments_text())


def test_duplicate_instrument_names_are_rejected() -> None:
    with pytest.raises(LabProfileError, match="unique"):
        parse_lab_profile(_duplicate_names_text())


def test_non_utf8_file_is_rejected(tmp_path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_bytes(b"\xff\xfe\x00 not utf-8")
    with pytest.raises(LabProfileError, match="strict UTF-8"):
        load_lab_profile(broken)


def test_whitespace_only_display_name_is_rejected() -> None:
    with pytest.raises(LabProfileError, match="whitespace-only"):
        parse_lab_profile(_base().replace("display_name: Hostile Lab", 'display_name: "   "'))


def test_whitespace_only_question_fields_are_rejected() -> None:
    blank_subject = _with_questions('questions:\n  - kind: class_a_thresholds\n    subject: "  "\n    summary: s\n')
    with pytest.raises(LabProfileError, match="whitespace-only"):
        parse_lab_profile(blank_subject)
    blank_summary = _with_questions('questions:\n  - kind: class_a_thresholds\n    subject: s\n    summary: "   "\n')
    with pytest.raises(LabProfileError, match="whitespace-only"):
        parse_lab_profile(blank_summary)


def test_identity_limit_counts_characters_not_bytes() -> None:
    accepted = _base().replace("lab_id: hostile-lab", f"lab_id: {'я' * 64}")
    assert parse_lab_profile(accepted).lab_id == "я" * 64
    rejected = _base().replace("lab_id: hostile-lab", f"lab_id: {'я' * 65}")
    with pytest.raises(LabProfileError, match="64 characters"):
        parse_lab_profile(rejected)


def test_lab_capabilities_must_equal_the_registry_derivation() -> None:
    invented = dict(
        instrument_types=("lakeshore_218s",),
        capabilities=frozenset({DriverCapability.CALIBRATABLE_SENSOR}),
        trust_classes=frozenset({DriverAuthority.PASSIVE_MEASUREMENT}),
    )
    with pytest.raises(LabProfileError, match="derived from INSTRUMENT_DRIVER_METADATA"):
        LabCapabilities(**invented)
    unknown_type = dict(
        instrument_types=("not_a_driver",),
        capabilities=frozenset({DriverCapability.CALIBRATABLE_SENSOR}),
        trust_classes=frozenset({DriverAuthority.PASSIVE_MEASUREMENT}),
    )
    with pytest.raises(LabProfileError, match="closed allowlist"):
        LabCapabilities(**unknown_type)
    source_type = dict(
        instrument_types=("keithley_2604b",),
        capabilities=frozenset(
            {
                DriverCapability.PASSIVE_SENSOR,
                DriverCapability.CONTROLLED_SOURCE,
                DriverCapability.VERIFIED_OFF_SOURCE,
            }
        ),
        trust_classes=frozenset({DriverAuthority.REVIEWED_SOURCE}),
    )
    with pytest.raises(ActuationBoundaryError, match="hazardous actuator"):
        LabCapabilities(**source_type)
    honest = LabCapabilities(
        instrument_types=("lakeshore_218s",),
        capabilities=frozenset({DriverCapability.PASSIVE_SENSOR}),
        trust_classes=frozenset({DriverAuthority.PASSIVE_MEASUREMENT}),
    )
    assert honest.actuation_supported is False


def test_lab_capabilities_freezes_mutable_inputs() -> None:
    mutable_types = ["lakeshore_218s"]
    mutable_caps = {DriverCapability.PASSIVE_SENSOR}
    mutable_trust = {DriverAuthority.PASSIVE_MEASUREMENT}
    honest = LabCapabilities(
        instrument_types=mutable_types,
        capabilities=mutable_caps,
        trust_classes=mutable_trust,
    )
    mutable_types.append("keithley_2604b")
    mutable_caps.add(DriverCapability.CONTROLLED_SOURCE)
    mutable_trust.add(DriverAuthority.REVIEWED_SOURCE)
    assert tuple(honest.instrument_types) == ("lakeshore_218s",)
    assert honest.capabilities == frozenset({DriverCapability.PASSIVE_SENSOR})
    assert honest.trust_classes == frozenset({DriverAuthority.PASSIVE_MEASUREMENT})


def test_line_and_paragraph_separators_are_rejected_in_text() -> None:
    separated = _base().replace("display_name: Hostile Lab", 'display_name: "Hostile\\u2028Lab"')
    with pytest.raises(LabProfileError, match="line/paragraph separator"):
        parse_lab_profile(separated)
    forged = _with_questions(
        'questions:\n  - kind: class_a_thresholds\n    subject: s\n    summary: "x\\u2029actuation_supported: true"\n'
    )
    with pytest.raises(LabProfileError, match="line/paragraph separator"):
        parse_lab_profile(forged)


def test_parse_lab_profile_enforces_the_byte_ceiling_on_text() -> None:
    oversized = f"# {'x' * (70 * 1024)}\n{_base()}"
    with pytest.raises(LabProfileError, match="bounded text grammar"):
        parse_lab_profile(oversized)
    within = f"# {'y' * (8 * 1024)}\n{_base()}"
    assert parse_lab_profile(within).lab_id == "hostile-lab"


def test_parse_lab_profile_rejects_unpaired_surrogates_with_lab_profile_error() -> None:
    broken = _base().replace("display_name: Hostile Lab", "display_name: " + "\ud800")
    with pytest.raises(LabProfileError):
        parse_lab_profile(broken)
