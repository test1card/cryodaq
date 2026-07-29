"""Fail-closed signed qualification boundary for release artifacts."""

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

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from cryodaq.core.qualification import (  # noqa: E402
    QualificationReceiptError,
    verify_artifact_qualification_receipt,
)

_GIT_OBJECT = re.compile(r"[0-9a-f]{40}\Z")


class PromotionRefused(ValueError):
    """The candidate is not eligible for release promotion."""


def artifact_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise PromotionRefused("artifact must be one regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _receipt_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PromotionRefused("qualification receipt is missing or not a regular file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PromotionRefused("qualification receipt is unreadable") from exc


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
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
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


def validate_receipt(
    artifact: Path,
    receipt_path: Path,
    *,
    commit: str,
    tree: str,
    replay_directory: Path,
) -> dict[str, str]:
    if not _GIT_OBJECT.fullmatch(commit) or not _GIT_OBJECT.fullmatch(tree):
        raise PromotionRefused("candidate commit and tree must be full lowercase Git object IDs")
    if replay_directory.is_symlink():
        raise PromotionRefused("qualification replay directory must not be a symlink")
    version = validate_unqualified_marker(artifact)
    digest = artifact_digest(artifact)
    try:
        receipt = verify_artifact_qualification_receipt(
            _receipt_bytes(receipt_path),
            expected_commit=commit,
            expected_tree=tree,
            expected_artifact_sha256=digest,
            replay_directory=replay_directory,
        )
    except (OSError, QualificationReceiptError, ValueError) as exc:
        raise PromotionRefused(f"qualification receipt verification failed: {exc}") from exc
    return {
        "artifact_digest": receipt.context.artifact_sha256,
        "configuration_digest": receipt.context.configuration_sha256,
        "hardware_profile_id": receipt.context.hardware_profile_id,
        "reviewed_source_binding_digest": receipt.context.reviewed_source_binding_sha256,
        "version": version,
    }


def promote(
    artifact: Path,
    receipt: Path,
    output_dir: Path,
    *,
    commit: str,
    tree: str,
    replay_directory: Path,
) -> Path:
    result = validate_receipt(
        artifact,
        receipt,
        commit=commit,
        tree=tree,
        replay_directory=replay_directory,
    )
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
    promote_parser.add_argument("--replay-directory", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            version = validate_unqualified_marker(args.artifact)
            print(json.dumps({"status": "UNQUALIFIED", "version": version}, sort_keys=True))
        else:
            promote(
                args.artifact,
                args.receipt,
                args.output_dir,
                commit=args.commit,
                tree=args.tree,
                replay_directory=args.replay_directory,
            )
    except PromotionRefused as exc:
        print(f"PROMOTION_GATE_REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
