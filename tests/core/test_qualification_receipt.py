from __future__ import annotations

from pathlib import Path

import pytest

from cryodaq.core.qualification import (
    QualificationReceiptError,
    is_issued_qualification_receipt,
    verify_artifact_qualification_receipt,
    verify_qualification_receipt,
)
from tests.qualification_support import (
    PAYLOAD,
    SIGNATURE,
    VALID_AT,
    qualification_context,
    qualification_receipt_bytes,
)


def test_valid_signed_receipt_issues_exact_sealed_authority(tmp_path: Path) -> None:
    receipt = verify_qualification_receipt(
        qualification_receipt_bytes(),
        expected=qualification_context(),
        replay_directory=tmp_path,
        now_unix_s=VALID_AT,
    )

    assert is_issued_qualification_receipt(receipt)
    assert receipt.context == qualification_context()
    assert receipt.receipt_id == PAYLOAD["receipt_id"]


@pytest.mark.parametrize(
    "raw",
    (
        b"{",
        b"",
        qualification_receipt_bytes().replace(SIGNATURE.encode(), b"***"),
        b'{"unknown":true}',
        b'{"schema":"cryodaq-lab-qualification-v1","schema":"cryodaq-lab-qualification-v1"}',
    ),
)
def test_malformed_receipt_is_refused_without_consuming_authority(tmp_path: Path, raw: bytes) -> None:
    with pytest.raises(QualificationReceiptError):
        verify_qualification_receipt(
            raw,
            expected=qualification_context(),
            replay_directory=tmp_path,
            now_unix_s=VALID_AT,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("field", "wrong"),
    (
        ("commit", "0" * 40),
        ("tree", "0" * 40),
        ("artifact_sha256", "sha256:" + "00" * 32),
        ("configuration_sha256", "sha256:" + "00" * 32),
        ("reviewed_source_binding_sha256", "sha256:" + "00" * 32),
        ("hardware_profile_id", "different-hardware"),
    ),
)
def test_signed_receipt_for_wrong_runtime_context_is_refused(
    tmp_path: Path,
    field: str,
    wrong: str,
) -> None:
    with pytest.raises(QualificationReceiptError, match="exact runtime context"):
        verify_qualification_receipt(
            qualification_receipt_bytes(),
            expected=qualification_context(**{field: wrong}),
            replay_directory=tmp_path,
            now_unix_s=VALID_AT,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("now", (PAYLOAD["issued_at_unix_s"] - 1, PAYLOAD["expires_at_unix_s"]))
def test_stale_or_not_yet_valid_receipt_is_refused(tmp_path: Path, now: int) -> None:
    with pytest.raises(QualificationReceiptError, match="stale or not yet valid"):
        verify_qualification_receipt(
            qualification_receipt_bytes(),
            expected=qualification_context(),
            replay_directory=tmp_path,
            now_unix_s=now,
        )


def test_consumed_receipt_cannot_be_replayed(tmp_path: Path) -> None:
    first = verify_qualification_receipt(
        qualification_receipt_bytes(),
        expected=qualification_context(),
        replay_directory=tmp_path,
        now_unix_s=VALID_AT,
    )
    assert is_issued_qualification_receipt(first)

    with pytest.raises(QualificationReceiptError, match="replay refused"):
        verify_qualification_receipt(
            qualification_receipt_bytes(),
            expected=qualification_context(),
            replay_directory=tmp_path,
            now_unix_s=VALID_AT,
        )


def test_artifact_boundary_refuses_current_promotion_with_expired_root_vector(tmp_path: Path) -> None:
    with pytest.raises(QualificationReceiptError, match="stale or not yet valid"):
        verify_artifact_qualification_receipt(
            qualification_receipt_bytes(),
            expected_commit=str(PAYLOAD["commit"]),
            expected_tree=str(PAYLOAD["tree"]),
            expected_artifact_sha256=str(PAYLOAD["artifact_sha256"]),
            replay_directory=tmp_path,
        )
