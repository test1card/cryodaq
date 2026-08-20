"""Fail-closed laboratory-qualification receipt authority.

The tracked default branch has no receipt and therefore remains UNQUALIFIED.
Receipt signing is deliberately external: this module contains only the public
verification root and an expired, non-deployable test vector.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from cryodaq.drivers.contracts import DriverRuntimeBinding, is_issued_runtime_binding

_SCHEMA: Final = "cryodaq-lab-qualification-v1"
_KEY_ID: Final = "cryodaq-lab-qualification-rsa-v1"
_MAX_RECEIPT_BYTES: Final = 16_384
_MAX_RECEIPT_LIFETIME_S: Final = 24 * 60 * 60
_RSA_PUBLIC_EXPONENT: Final = 65_537
_RSA_PUBLIC_MODULUS: Final = int(
    "a082a36fffc15cf0a2499e555e4a39e7d9d6f01fa9e73742c2ac9ab1773141d"
    "ad5740d5f2c9ea2438612c800f2be571c1a953b39f3ca3a1ad615f287796bfc06"
    "81b025c0c06531b16dc9b4d2fda28abaf0eecf264411d6e6725f0b4e6b148386"
    "fe5397a5af99b6c8ee6efded46f5c856b4a038f04d48fe3b4450f02c0a7fd6fb"
    "85b9b667b00e92bcbb9447cefa0b2b3a295615b980f1c3208df9f2038dcd8747"
    "d620112adccc886c6e87ad3717ca1b66726e7bdb43483072da636f57db2e5b687"
    "294f1eeac62f75ad1fe2c99070635e30f4c7989ae0d991612bdff887dcb5ebf0a"
    "5760db95f33bba6435f3057b30f9e788e0d95303d2c49a8720b472b998a65b",
    16,
)
_RSA_SHA256_DIGEST_INFO: Final = bytes.fromhex("3031300d060960864801650304020105000420")
_SHA256_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_ID_RE: Final = re.compile(r"[0-9a-f]{40}")
_RECEIPT_ID_RE: Final = re.compile(r"[0-9a-f]{32}")
_PROFILE_ID_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_PAYLOAD_KEYS: Final = frozenset(
    {
        "schema",
        "key_id",
        "receipt_id",
        "commit",
        "tree",
        "artifact_sha256",
        "configuration_sha256",
        "reviewed_source_binding_sha256",
        "hardware_profile_id",
        "issued_at_unix_s",
        "expires_at_unix_s",
    }
)
_RECEIPT_KEYS: Final = _PAYLOAD_KEYS | {"signature"}
_QUALIFICATION_SEAL: Final = object()


class QualificationReceiptError(RuntimeError):
    """A receipt did not establish exact, current qualification authority."""


@dataclass(frozen=True, slots=True)
class QualificationContext:
    """Exact runtime facts a laboratory receipt must bind."""

    commit: str
    tree: str
    artifact_sha256: str
    configuration_sha256: str
    reviewed_source_binding_sha256: str
    hardware_profile_id: str

    def __post_init__(self) -> None:
        if _GIT_ID_RE.fullmatch(self.commit) is None or _GIT_ID_RE.fullmatch(self.tree) is None:
            raise ValueError("qualification commit and tree must be lowercase 40-hex Git identities")
        for name in ("artifact_sha256", "configuration_sha256", "reviewed_source_binding_sha256"):
            if _SHA256_RE.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a lowercase sha256 digest")
        if _PROFILE_ID_RE.fullmatch(self.hardware_profile_id) is None:
            raise ValueError("hardware_profile_id is malformed")


@dataclass(frozen=True, slots=True, init=False)
class QualificationReceipt:
    """Sealed authority created only after signature, binding, time, and replay checks."""

    receipt_id: str
    expires_at_unix_s: int
    expires_monotonic_s: float
    context: QualificationContext
    _seal: object

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("QualificationReceipt is issued only by verify_qualification_receipt")

    @classmethod
    def _issued(
        cls,
        *,
        receipt_id: str,
        expires_at_unix_s: int,
        expires_monotonic_s: float,
        context: QualificationContext,
    ) -> QualificationReceipt:
        instance = object.__new__(cls)
        object.__setattr__(instance, "receipt_id", receipt_id)
        object.__setattr__(instance, "expires_at_unix_s", expires_at_unix_s)
        object.__setattr__(instance, "expires_monotonic_s", expires_monotonic_s)
        object.__setattr__(instance, "context", context)
        object.__setattr__(instance, "_seal", _QUALIFICATION_SEAL)
        return instance


def is_issued_qualification_receipt(value: object) -> bool:
    return isinstance(value, QualificationReceipt) and value._seal is _QUALIFICATION_SEAL


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationReceiptError(f"duplicate qualification receipt key: {key}")
        result[key] = value
    return result


def _canonical_payload(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _signature_valid(payload: bytes, signature_text: object) -> bool:
    if not isinstance(signature_text, str):
        return False
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (binascii.Error, ValueError):
        return False
    size = (_RSA_PUBLIC_MODULUS.bit_length() + 7) // 8
    if len(signature) != size:
        return False
    encoded = pow(int.from_bytes(signature, "big"), _RSA_PUBLIC_EXPONENT, _RSA_PUBLIC_MODULUS).to_bytes(size, "big")
    digest = hashlib.sha256(payload).digest()
    padding_size = size - len(_RSA_SHA256_DIGEST_INFO) - len(digest) - 3
    expected = b"\x00\x01" + b"\xff" * padding_size + b"\x00" + _RSA_SHA256_DIGEST_INFO + digest
    return secrets.compare_digest(encoded, expected)


def _strict_receipt(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > _MAX_RECEIPT_BYTES:
        raise QualificationReceiptError("qualification receipt is empty or oversized")
    try:
        decoded = raw.decode("utf-8")
        receipt = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationReceiptError("qualification receipt is not strict UTF-8 JSON") from exc
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS:
        raise QualificationReceiptError("qualification receipt has missing or unknown fields")
    return receipt


def _require_exact_fields(receipt: Mapping[str, object]) -> None:
    if receipt["schema"] != _SCHEMA or receipt["key_id"] != _KEY_ID:
        raise QualificationReceiptError("qualification receipt schema or verification key is wrong")
    if not isinstance(receipt["receipt_id"], str) or _RECEIPT_ID_RE.fullmatch(receipt["receipt_id"]) is None:
        raise QualificationReceiptError("qualification receipt_id is malformed")
    for field in ("commit", "tree"):
        if not isinstance(receipt[field], str) or _GIT_ID_RE.fullmatch(receipt[field]) is None:
            raise QualificationReceiptError(f"qualification {field} is malformed")
    for field in ("artifact_sha256", "configuration_sha256", "reviewed_source_binding_sha256"):
        if not isinstance(receipt[field], str) or _SHA256_RE.fullmatch(receipt[field]) is None:
            raise QualificationReceiptError(f"qualification {field} is malformed")
    profile_id = receipt["hardware_profile_id"]
    if not isinstance(profile_id, str) or _PROFILE_ID_RE.fullmatch(profile_id) is None:
        raise QualificationReceiptError("qualification hardware_profile_id is malformed")
    for field in ("issued_at_unix_s", "expires_at_unix_s"):
        if type(receipt[field]) is not int:
            raise QualificationReceiptError(f"qualification {field} must be an integer")


def _consume_once(replay_directory: Path, receipt_id: str, payload_digest: str) -> None:
    try:
        replay_directory.mkdir(parents=True, exist_ok=True)
        marker = replay_directory / f"{receipt_id}.used"
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, (payload_digest + "\n").encode("ascii"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except FileExistsError as exc:
        raise QualificationReceiptError("qualification receipt was already consumed (replay refused)") from exc
    except OSError as exc:
        raise QualificationReceiptError("qualification replay store is unavailable") from exc


def verify_qualification_receipt(
    raw: bytes,
    *,
    expected: QualificationContext,
    replay_directory: Path,
    now_unix_s: int | None = None,
) -> QualificationReceipt:
    """Verify and durably consume one exact activation receipt."""

    receipt = _strict_receipt(raw)
    _require_exact_fields(receipt)
    payload = {key: receipt[key] for key in _PAYLOAD_KEYS}
    canonical = _canonical_payload(payload)
    if not _signature_valid(canonical, receipt["signature"]):
        raise QualificationReceiptError("qualification receipt signature is invalid")

    actual = QualificationContext(
        commit=str(receipt["commit"]),
        tree=str(receipt["tree"]),
        artifact_sha256=str(receipt["artifact_sha256"]),
        configuration_sha256=str(receipt["configuration_sha256"]),
        reviewed_source_binding_sha256=str(receipt["reviewed_source_binding_sha256"]),
        hardware_profile_id=str(receipt["hardware_profile_id"]),
    )
    if actual != expected:
        raise QualificationReceiptError("qualification receipt does not match the exact runtime context")

    issued = int(receipt["issued_at_unix_s"])
    expires = int(receipt["expires_at_unix_s"])
    now = int(time.time()) if now_unix_s is None else now_unix_s
    if expires <= issued or expires - issued > _MAX_RECEIPT_LIFETIME_S:
        raise QualificationReceiptError("qualification receipt lifetime is malformed")
    if now < issued or now >= expires:
        raise QualificationReceiptError("qualification receipt is stale or not yet valid")

    payload_digest = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    receipt_id = str(receipt["receipt_id"])
    _consume_once(replay_directory, receipt_id, payload_digest)
    return QualificationReceipt._issued(
        receipt_id=receipt_id,
        expires_at_unix_s=expires,
        expires_monotonic_s=time.monotonic() + (expires - now),
        context=actual,
    )


def verify_artifact_qualification_receipt(
    raw: bytes,
    *,
    expected_commit: str,
    expected_tree: str,
    expected_artifact_sha256: str,
    replay_directory: Path,
) -> QualificationReceipt:
    """Verify the signed receipt facts an artifact boundary can remeasure."""

    receipt = _strict_receipt(raw)
    _require_exact_fields(receipt)
    actual = QualificationContext(
        commit=str(receipt["commit"]),
        tree=str(receipt["tree"]),
        artifact_sha256=str(receipt["artifact_sha256"]),
        configuration_sha256=str(receipt["configuration_sha256"]),
        reviewed_source_binding_sha256=str(receipt["reviewed_source_binding_sha256"]),
        hardware_profile_id=str(receipt["hardware_profile_id"]),
    )
    if (
        actual.commit != expected_commit
        or actual.tree != expected_tree
        or actual.artifact_sha256 != expected_artifact_sha256
    ):
        raise QualificationReceiptError("qualification receipt does not match the exact artifact context")
    return verify_qualification_receipt(
        raw,
        expected=actual,
        replay_directory=replay_directory,
    )


def _manifest_digest(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        raw = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return f"sha256:{digest.hexdigest()}"


def source_artifact_paths(project_root: Path) -> list[Path]:
    """Every file whose bytes the artifact digest measures, in one place.

    It was written inline inside the qualification context, which meant the ONLY way to
    know what had been measured was to run the qualification again. The plugin pipeline
    has to ask the same question immediately before it imports, so the answer lives here
    and both callers use it.

    WHY EXCLUDING `__pycache__` AND `.pyc` IS SAFE, and what it depends on. A cache entry
    is selected whenever the source size and modification time it records still agree, so
    a same-size or same-second edit leaves stale bytecode selectable while the measured
    `.py` reads as new. Excluding the cache from the digest therefore only holds while
    nothing qualified EXECUTES a cache entry. That is enforced at the one place that
    imports: `PluginPipeline._load_plugin` compiles the measured bytes for a qualified run
    and never goes through the import machinery. Do not relax that without measuring
    bytecode here as well.
    """

    package_root = project_root / "src" / "cryodaq"
    if not package_root.is_dir():
        raise QualificationReceiptError("source package manifest is unavailable")

    def _measured(root: Path) -> list[Path]:
        return [
            path
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
        ]

    package_paths = _measured(package_root)
    if not package_paths:
        raise QualificationReceiptError("source package manifest is empty")
    plugins_root = project_root / "plugins"
    return package_paths + (_measured(plugins_root) if plugins_root.is_dir() else [])


def source_artifact_digest(project_root: Path) -> str:
    """The artifact digest of the tree AS IT IS NOW."""

    return _manifest_digest(project_root, source_artifact_paths(project_root))


def source_checkout_qualification_context(
    *,
    project_root: Path,
    config_directory: Path,
    reviewed_source: object,
    runtime_binding: DriverRuntimeBinding,
    instrument_configuration_path: Path | None = None,
) -> QualificationContext:
    """Measure an unfrozen source checkout; frozen builds need packaging evidence."""

    if getattr(sys, "frozen", False):
        raise QualificationReceiptError("frozen artifact identity requires the separately owned packaging hook")
    if not is_issued_runtime_binding(runtime_binding) or runtime_binding.driver is not reviewed_source:
        raise QualificationReceiptError("reviewed-source runtime binding is not exact and issued")

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualificationReceiptError("source build identity is unavailable") from exc

    artifact_paths = source_artifact_paths(project_root)
    config_paths = [
        path for path in config_directory.rglob("*") if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}
    ]
    if not artifact_paths or not config_paths:
        raise QualificationReceiptError("source artifact or configuration manifest is empty")

    artifact_sha256 = _manifest_digest(project_root, artifact_paths)
    configuration_sha256 = _manifest_digest(config_directory, config_paths)
    binding_payload = _canonical_payload(
        {
            "driver_class": f"{type(reviewed_source).__module__}.{type(reviewed_source).__qualname__}",
            "driver_mock": getattr(reviewed_source, "mock", None),
            "registry_provenance": runtime_binding.registry_provenance,
            "simulation": runtime_binding.simulation,
            "timing": {
                "connect_timeout_s": runtime_binding.timing.connect_timeout_s,
                "poll_interval_s": runtime_binding.timing.poll_interval_s,
                "read_timeout_s": runtime_binding.timing.read_timeout_s,
            },
            "trust_class": runtime_binding.trust_class.value,
        }
    )
    binding_sha256 = f"sha256:{hashlib.sha256(binding_payload).hexdigest()}"
    instruments_path = instrument_configuration_path or config_directory / "instruments.yaml"
    if not instruments_path.is_file():
        raise QualificationReceiptError("hardware profile manifest is unavailable")
    hardware_digest = hashlib.sha256(instruments_path.read_bytes()).hexdigest()
    return QualificationContext(
        commit=commit,
        tree=tree,
        artifact_sha256=artifact_sha256,
        configuration_sha256=configuration_sha256,
        reviewed_source_binding_sha256=binding_sha256,
        hardware_profile_id=f"cryodaq-hardware-{hardware_digest[:32]}",
    )


__all__ = [
    "QualificationContext",
    "QualificationReceipt",
    "QualificationReceiptError",
    "is_issued_qualification_receipt",
    "source_checkout_qualification_context",
    "verify_artifact_qualification_receipt",
    "verify_qualification_receipt",
]
