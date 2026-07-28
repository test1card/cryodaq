"""Fail-closed qualification-receipt boundary for release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import UNQUALIFIED_LABEL, UNQUALIFIED_LOCAL_VERSION
except ImportError:
    from artifact_identity import UNQUALIFIED_LABEL, UNQUALIFIED_LOCAL_VERSION

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GIT_OBJECT = re.compile(r"[0-9a-f]{40}\Z")
_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_RECEIPT_FIELDS = {
    "artifact_digest",
    "binding_digest",
    "commit",
    "config_digest",
    "hardware_profile_id",
    "schema_version",
    "tree",
}
_MAX_RECEIPT_BYTES = 64 * 1024


class PromotionRefused(ValueError):
    """The candidate is not eligible for release promotion."""


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def artifact_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise PromotionRefused("artifact must be one regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def receipt_binding_digest(receipt: dict[str, Any]) -> str:
    bound = {key: value for key, value in receipt.items() if key != "binding_digest"}
    raw = (json.dumps(bound, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return _sha256_bytes(raw)


def _read_receipt(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PromotionRefused("qualification receipt is missing or not a regular file")
    raw = path.read_bytes()
    if len(raw) > _MAX_RECEIPT_BYTES:
        raise PromotionRefused("qualification receipt exceeds 64 KiB")
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionRefused("qualification receipt is not valid UTF-8 JSON") from exc
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
        raise PromotionRefused("qualification receipt schema fields are not exact")
    return receipt


def _wheel_metadata(archive: zipfile.ZipFile) -> str:
    paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
    if len(paths) != 1:
        raise PromotionRefused("wheel must contain exactly one METADATA file")
    return archive.read(paths[0]).decode("utf-8")


def _onedir_marker(archive: zipfile.ZipFile) -> dict[str, Any]:
    paths = [name for name in archive.namelist() if name.endswith("/ARTIFACT_STATUS.json")]
    if len(paths) != 1:
        raise PromotionRefused("ONEDIR zip must contain exactly one ARTIFACT_STATUS.json")
    try:
        marker = json.loads(archive.read(paths[0]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionRefused("ONEDIR artifact marker is not valid UTF-8 JSON") from exc
    return marker


def validate_unqualified_marker(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            if path.suffix.lower() == ".whl":
                metadata = _wheel_metadata(archive)
                version = next(
                    (line.removeprefix("Version: ") for line in metadata.splitlines() if line.startswith("Version: ")),
                    "",
                )
                if UNQUALIFIED_LABEL not in metadata or not version.endswith(f"+{UNQUALIFIED_LOCAL_VERSION}"):
                    raise PromotionRefused("wheel metadata does not declare UNQUALIFIED — TEST ONLY")
                return version
            if path.suffix.lower() != ".zip":
                raise PromotionRefused("only wheel or ONEDIR zip artifacts may be promoted")
            marker = _onedir_marker(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PromotionRefused("artifact is not a readable wheel or ONEDIR zip") from exc

    expected_keys = {"label", "schema_version", "status", "version"}
    if not isinstance(marker, dict) or set(marker) != expected_keys:
        raise PromotionRefused("ONEDIR artifact marker schema fields are not exact")
    version = marker["version"]
    if (
        marker["schema_version"] != 1
        or marker["status"] != "unqualified"
        or marker["label"] != UNQUALIFIED_LABEL
        or not isinstance(version, str)
        or not version.endswith(f"+{UNQUALIFIED_LOCAL_VERSION}")
    ):
        raise PromotionRefused("ONEDIR artifact does not declare UNQUALIFIED — TEST ONLY")
    return version


def validate_receipt(artifact: Path, receipt_path: Path, *, commit: str, tree: str) -> dict[str, Any]:
    if not _GIT_OBJECT.fullmatch(commit) or not _GIT_OBJECT.fullmatch(tree):
        raise PromotionRefused("candidate commit and tree must be full lowercase Git object IDs")
    version = validate_unqualified_marker(artifact)
    receipt = _read_receipt(receipt_path)
    if receipt["schema_version"] != 1:
        raise PromotionRefused("qualification receipt schema version is unsupported")
    if receipt["commit"] != commit or receipt["tree"] != tree:
        raise PromotionRefused("qualification receipt does not match candidate commit and tree")
    if receipt["artifact_digest"] != artifact_digest(artifact):
        raise PromotionRefused("qualification receipt does not match artifact digest")
    if not isinstance(receipt["config_digest"], str) or not _DIGEST.fullmatch(receipt["config_digest"]):
        raise PromotionRefused("qualification receipt config digest is invalid")
    profile = receipt["hardware_profile_id"]
    if not isinstance(profile, str) or not _PROFILE.fullmatch(profile):
        raise PromotionRefused("qualification receipt hardware profile ID is invalid")
    if receipt["binding_digest"] != receipt_binding_digest(receipt):
        raise PromotionRefused("qualification receipt binding digest is invalid")
    return {"artifact_digest": receipt["artifact_digest"], "hardware_profile_id": profile, "version": version}


def promote(artifact: Path, receipt: Path, output_dir: Path, *, commit: str, tree: str) -> Path:
    result = validate_receipt(artifact, receipt, commit=commit, tree=tree)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / artifact.name
    if destination.exists():
        raise PromotionRefused("promotion output already exists")
    shutil.copy2(artifact, destination)
    if artifact_digest(destination) != result["artifact_digest"]:
        destination.unlink(missing_ok=True)
        raise PromotionRefused("promoted copy does not match qualified artifact digest")
    print(
        json.dumps(
            {"status": "PROMOTED", "path": str(destination), **result},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    command = parser.add_subparsers(dest="command", required=True)
    inspect = command.add_parser("inspect", allow_abbrev=False)
    inspect.add_argument("--artifact", required=True, type=Path)
    promote_parser = command.add_parser("promote", allow_abbrev=False)
    promote_parser.add_argument("--artifact", required=True, type=Path)
    promote_parser.add_argument("--receipt", required=True, type=Path)
    promote_parser.add_argument("--output-dir", required=True, type=Path)
    promote_parser.add_argument("--commit", required=True)
    promote_parser.add_argument("--tree", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            version = validate_unqualified_marker(args.artifact)
            print(json.dumps({"status": "UNQUALIFIED", "version": version}, sort_keys=True))
        else:
            promote(args.artifact, args.receipt, args.output_dir, commit=args.commit, tree=args.tree)
    except PromotionRefused as exc:
        print(f"PROMOTION_GATE_REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
