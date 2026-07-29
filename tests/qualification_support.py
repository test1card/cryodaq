"""Expired signed qualification vector for production-path tests only."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from cryodaq.core.qualification import QualificationContext, QualificationReceipt, verify_qualification_receipt
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverRuntimeBinding,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)

VALID_AT = 946_685_000
PAYLOAD = {
    "schema": "cryodaq-lab-qualification-v1",
    "key_id": "cryodaq-lab-qualification-rsa-v1",
    "receipt_id": "4d4f434b5155414c494649434154494f",
    "commit": "f190bc5be647ea8d9f82e8c82ce6049074219722",
    "tree": "8272fe337a02c4f18198bbe880bbf5e2fcf22718",
    "artifact_sha256": "sha256:" + "11" * 32,
    "configuration_sha256": "sha256:" + "22" * 32,
    "reviewed_source_binding_sha256": "sha256:" + "33" * 32,
    "hardware_profile_id": "cryodaq-expired-test-stand-v1",
    "issued_at_unix_s": 946_684_800,
    "expires_at_unix_s": 946_688_400,
}
SIGNATURE = (
    "Rw+lAmv3Jf8bwYSq0BFAQnLCVIIfXI+cxfw+90mzi4JHmELhVMiDXniBrrbRdBchaIDx6BlXAF3sHgXReVOAH6E7"
    "As/pJ77Qvrkto2A/2UCzGJnlYO4JY6ipyl1pspGyuUrskxv2GcD65jor7NRh1UScbEGfuz+uLOo9/89PtIzMkrZB2"
    "ZVSb5PJBHbQWRT7v/kQ4YiiWO9JbcDskSxT6rwhysEz9yeenu5H3XQu7uzjGOQnMk/w6aCrYe3K5h5mTPnSpXNsdr"
    "AIJvW+qoNbVvnfJ3wtGgDQRmNdQZpkjAQb1gEiKJRd40dVNi00Iu4Ws0i1GsDio8qaCQMLfmht9A=="
)


def qualification_context(**changes: str) -> QualificationContext:
    values = {
        key: value
        for key, value in PAYLOAD.items()
        if key
        in {
            "commit",
            "tree",
            "artifact_sha256",
            "configuration_sha256",
            "reviewed_source_binding_sha256",
            "hardware_profile_id",
        }
    }
    values.update(changes)
    return QualificationContext(**values)


def qualification_receipt_bytes() -> bytes:
    return (json.dumps(PAYLOAD | {"signature": SIGNATURE}, sort_keys=True) + "\n").encode()


def issued_test_qualification_receipt() -> QualificationReceipt:
    """Issue from an expired vector at its historical clock; never deployable."""

    with TemporaryDirectory() as directory:
        return verify_qualification_receipt(
            qualification_receipt_bytes(),
            expected=qualification_context(),
            replay_directory=Path(directory),
            now_unix_s=VALID_AT,
        )


def issued_simulation_binding(driver: object, provenance: str) -> DriverRuntimeBinding:
    """Issue the same exact-object simulation fact the production registry owns."""

    return _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance=provenance,
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
        simulation=True,
    )
