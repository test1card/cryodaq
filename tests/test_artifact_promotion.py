from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from build_scripts import artifact_promotion as promotion
from tests.qualification_support import qualification_receipt_bytes

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
TREE = "b" * 40


def _marker() -> dict[str, object]:
    return {
        "label": "UNQUALIFIED — TEST ONLY",
        "schema_version": 1,
        "status": "unqualified",
        "version": "0.64.1+checkpoint.unqualified",
    }


def _onedir_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("CryoDAQ/ARTIFACT_STATUS.json", json.dumps(_marker(), ensure_ascii=False))
        archive.writestr("CryoDAQ/CryoDAQ.exe", b"checkpoint")


def _wheel(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "cryodaq-0.64.1+checkpoint.unqualified.dist-info/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: cryodaq\n"
            "Version: 0.64.1+checkpoint.unqualified\n"
            "Summary: UNQUALIFIED — TEST ONLY\n",
        )


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _legacy_self_hash_receipt(artifact: Path) -> dict[str, object]:
    receipt: dict[str, object] = {
        "artifact_digest": promotion.artifact_digest(artifact),
        "binding_digest": "",
        "commit": COMMIT,
        "config_digest": "sha256:" + "c" * 64,
        "hardware_profile_id": "attacker-invented-profile",
        "schema_version": 1,
        "tree": TREE,
    }
    bound = {key: value for key, value in receipt.items() if key != "binding_digest"}
    raw = (json.dumps(bound, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    receipt["binding_digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return receipt


def _forged_signed_schema_receipt(artifact: Path) -> dict[str, object]:
    now = int(time.time())
    return {
        "schema": "cryodaq-lab-qualification-v1",
        "key_id": "cryodaq-lab-qualification-rsa-v1",
        "receipt_id": "f" * 32,
        "commit": COMMIT,
        "tree": TREE,
        "artifact_sha256": promotion.artifact_digest(artifact),
        "configuration_sha256": "sha256:" + "c" * 64,
        "reviewed_source_binding_sha256": "sha256:" + "d" * 64,
        "hardware_profile_id": "attacker-invented-profile",
        "issued_at_unix_s": now - 1,
        "expires_at_unix_s": now + 3600,
        "signature": base64.b64encode(b"\0" * 256).decode(),
    }


def test_post_build_marks_onedir_unqualified(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scripts = project / "build_scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "build_scripts" / "post_build.py", scripts / "post_build.py")
    shutil.copy2(ROOT / "build_scripts" / "artifact_identity.py", scripts / "artifact_identity.py")
    (project / "pyproject.toml").write_text('[project]\nversion = "0.64.1"\n', encoding="utf-8")
    (project / "config").mkdir()
    (project / "dist" / "CryoDAQ").mkdir(parents=True)
    (project / "LICENSE").write_text("test", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(scripts / "post_build.py")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    marker = project / "dist" / "CryoDAQ" / "ARTIFACT_STATUS.json"
    assert json.loads(marker.read_text(encoding="utf-8")) == _marker()


def test_wheel_presented_for_promotion_must_self_identify(tmp_path: Path) -> None:
    wheel = tmp_path / "cryodaq-0.64.1+checkpoint.unqualified-py3-none-any.whl"
    _wheel(wheel)

    assert promotion.validate_unqualified_marker(wheel) == "0.64.1+checkpoint.unqualified"


def test_promotion_without_receipt_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    artifact = tmp_path / "CryoDAQ-checkpoint.unqualified.zip"
    _onedir_zip(artifact)

    result = promotion.main(
        [
            "promote",
            "--artifact",
            str(artifact),
            "--receipt",
            str(tmp_path / "missing.json"),
            "--output-dir",
            str(tmp_path / "promoted"),
            "--commit",
            COMMIT,
            "--tree",
            TREE,
            "--replay-directory",
            str(tmp_path / "promotion-replay"),
        ]
    )

    assert result == 2
    assert capsys.readouterr().err == (
        "PROMOTION_GATE_REFUSED: qualification receipt verification failed: "
        "qualification receipt is missing or not a regular file\n"
    )


def test_promotion_with_wrong_artifact_digest_is_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = tmp_path / "CryoDAQ-checkpoint.unqualified.zip"
    receipt_path = tmp_path / "qualification.json"
    _onedir_zip(artifact)
    receipt_path.write_bytes(qualification_receipt_bytes())

    result = promotion.main(
        [
            "promote",
            "--artifact",
            str(artifact),
            "--receipt",
            str(receipt_path),
            "--output-dir",
            str(tmp_path / "promoted"),
            "--commit",
            COMMIT,
            "--tree",
            TREE,
            "--replay-directory",
            str(tmp_path / "promotion-replay"),
        ]
    )

    assert result == 2
    assert capsys.readouterr().err == (
        "PROMOTION_GATE_REFUSED: qualification receipt verification failed: "
        "qualification receipt does not match the exact artifact context\n"
    )


def test_oc_037_legacy_self_hash_forgery_is_refused(tmp_path: Path) -> None:
    artifact = tmp_path / "cryodaq-0.0.0-py3-none-any.whl"
    receipt = tmp_path / "forged.json"
    output = tmp_path / "promoted"
    _wheel(artifact)
    _write_receipt(receipt, _legacy_self_hash_receipt(artifact))

    with pytest.raises(promotion.PromotionRefused, match="missing or unknown fields"):
        promotion.promote(
            artifact,
            receipt,
            output,
            commit=COMMIT,
            tree=TREE,
            replay_directory=tmp_path / "promotion-replay",
        )

    assert not output.exists()


def test_new_schema_without_laboratory_signature_is_refused(tmp_path: Path) -> None:
    artifact = tmp_path / "cryodaq-0.0.0-py3-none-any.whl"
    receipt = tmp_path / "forged.json"
    output = tmp_path / "promoted"
    _wheel(artifact)
    _write_receipt(receipt, _forged_signed_schema_receipt(artifact))

    with pytest.raises(promotion.PromotionRefused, match="signature is invalid"):
        promotion.promote(
            artifact,
            receipt,
            output,
            commit=COMMIT,
            tree=TREE,
            replay_directory=tmp_path / "promotion-replay",
        )

    assert not output.exists()


def test_p3_self_hash_verifier_is_not_a_transitional_api() -> None:
    assert not hasattr(promotion, "receipt_binding_digest")


def test_promotion_cli_requires_a_replay_ledger(tmp_path: Path) -> None:
    artifact = tmp_path / "cryodaq-0.0.0-py3-none-any.whl"
    _wheel(artifact)

    with pytest.raises(SystemExit) as exc_info:
        promotion.main(
            [
                "promote",
                "--artifact",
                str(artifact),
                "--receipt",
                str(tmp_path / "receipt.json"),
                "--output-dir",
                str(tmp_path / "promoted"),
                "--commit",
                COMMIT,
                "--tree",
                TREE,
            ]
        )

    assert exc_info.value.code == 2


def test_promotion_boundary_is_a_workflow_status() -> None:
    workflow = ROOT / ".github" / "workflows" / "qualified-artifact-promotion.yml"

    assert workflow.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "name: qualification receipt / promotion boundary" in text
    assert "vars.QUALIFICATION_WORKFLOW_ID" in text
    assert 'test "$(jq -r .conclusion <<<"$run_json")" = "success"' in text
    assert 'test "$(jq -r .head_sha <<<"$run_json")" = "$CANDIDATE_COMMIT"' in text
    assert 'test "$(jq -r .workflow_id <<<"$run_json")" = "$EXPECTED_QUALIFICATION_WORKFLOW_ID"' in text
    assert "python build_scripts/artifact_promotion.py promote" in text
    assert text.index("python build_scripts/artifact_promotion.py promote") < text.index("gh release upload")
    gate = text[text.index("- name: Qualification receipt gate (required)") : text.index("gh release upload")]
    assert "continue-on-error" not in gate
    assert "if: always()" not in gate
    assert all(
        "gh release upload" not in path.read_text(encoding="utf-8")
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
        if path != workflow
    )
