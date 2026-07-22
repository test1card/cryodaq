from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.candidate_evidence import (
    CandidateEvidenceError,
    execute_exported_candidate,
    git_tree_manifest,
    validate_candidate_manifest,
    validate_materializable_paths,
)


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _commit(repo: Path, message: str) -> str:
    _run("git", "add", "-A", cwd=repo)
    _run("git", "commit", "-m", message, cwd=repo)
    return _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()


@pytest.fixture
def candidate_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git", "init", cwd=repo)
    _run("git", "config", "user.name", "Candidate Evidence Test", cwd=repo)
    _run("git", "config", "user.email", "candidate@example.invalid", cwd=repo)
    _write(repo / "src" / "pkg" / "__init__.py", "")
    _write(repo / "src" / "pkg" / "main.py", "from pkg.dep import VALUE\n")
    _write(
        repo / "tests" / "test_main.py",
        "from pkg.main import VALUE\n\n\ndef test_value() -> None:\n    assert VALUE == 42\n",
    )
    _commit(repo, "candidate without dependency")
    return repo


def _pythonpath_env(repo: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src")
    return env


def test_candidate_tests_execute_exported_committed_tree(candidate_repo: Path, tmp_path: Path) -> None:
    _write(candidate_repo / "src" / "pkg" / "dep.py", "VALUE = 42\n")
    ambient = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_main.py"],
        cwd=candidate_repo,
        env=_pythonpath_env(candidate_repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert ambient.returncode == 0, ambient.stdout + ambient.stderr

    uncommitted = execute_exported_candidate(
        candidate_repo,
        "HEAD",
        command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_main.py"],
        destination=tmp_path / "export-missing",
    )
    assert uncommitted.returncode != 0
    assert "pkg.dep" in (uncommitted.stdout + uncommitted.stderr).decode("utf-8", errors="replace")
    assert not (uncommitted.export_root / "src" / "pkg" / "dep.py").exists()

    committed = _commit(candidate_repo, "commit dependency")
    complete = execute_exported_candidate(
        candidate_repo,
        committed,
        command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_main.py"],
        destination=tmp_path / "export-complete",
    )
    assert complete.returncode == 0, complete.stdout + complete.stderr
    assert complete.commit == committed
    assert complete.tree == _run("git", "rev-parse", f"{committed}^{{tree}}", cwd=candidate_repo).stdout.strip()


def _manifest_receipt(manifest) -> dict[str, object]:
    return {
        "commit": manifest.commit,
        "tree": manifest.tree,
        "manifest_sha256": manifest.sha256,
        "records": [{"path": record.path, "mode": record.mode, "blob": record.blob} for record in manifest.records],
    }


def _git_blob(data: bytes) -> str:
    framed = f"blob {len(data)}\0".encode("ascii") + data
    return hashlib.sha1(framed).hexdigest()


def test_manifest_rejects_dirty_or_missing_product_dependencies(candidate_repo: Path) -> None:
    _write(candidate_repo / "src" / "pkg" / "dep.py", "VALUE = 42\n")
    commit = _commit(candidate_repo, "complete candidate")
    manifest = git_tree_manifest(candidate_repo, commit)
    valid = _manifest_receipt(manifest)
    validate_candidate_manifest(candidate_repo, valid)

    missing = {**valid, "records": valid["records"][:-1]}
    with pytest.raises(CandidateEvidenceError, match="complete|record"):
        validate_candidate_manifest(candidate_repo, missing)

    dirty_path = candidate_repo / "src" / "pkg" / "dep.py"
    dirty_bytes = b"VALUE = 99\n"
    dirty_path.write_bytes(dirty_bytes)
    dirty = _manifest_receipt(manifest)
    for record in dirty["records"]:
        if record["path"] == "src/pkg/dep.py":
            record["blob"] = _git_blob(dirty_bytes)
    with pytest.raises(CandidateEvidenceError, match="exact committed tree"):
        validate_candidate_manifest(candidate_repo, dirty)

    extra = _manifest_receipt(manifest)
    extra["records"].append({"path": "src/pkg/untracked.py", "mode": "100644", "blob": _git_blob(b"VALUE = 7\n")})
    with pytest.raises(CandidateEvidenceError, match="complete|record"):
        validate_candidate_manifest(candidate_repo, extra)

    wrong_mode = _manifest_receipt(manifest)
    wrong_mode["records"][0]["mode"] = "100755"
    with pytest.raises(CandidateEvidenceError, match="exact committed tree"):
        validate_candidate_manifest(candidate_repo, wrong_mode)


def test_export_execution_sanitizes_test_selection_and_python_environment(
    candidate_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        candidate_repo / "tests" / "test_environment.py",
        "import os\n\n"
        "def test_environment_is_sanitized() -> None:\n"
        "    assert 'PYTEST_ADDOPTS' not in os.environ\n"
        "    assert 'PYTEST_PLUGINS' not in os.environ\n"
        "    assert 'PYTHONHOME' not in os.environ\n"
        "    assert os.environ['PYTHONUTF8'] == '1'\n"
        "    assert os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'\n",
    )
    commit = _commit(candidate_repo, "environment guard")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ignore=tests/test_environment.py")
    monkeypatch.setenv("PYTEST_PLUGINS", "ambient_selection_plugin")
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "bogus-python-home"))

    receipt = execute_exported_candidate(
        candidate_repo,
        commit,
        command=[
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_environment.py",
        ],
        destination=tmp_path / "export-sanitized",
    )

    assert receipt.returncode == 0, receipt.stdout + receipt.stderr


def test_receipt_hashes_exact_output_bytes_without_unicode_replacement(
    candidate_repo: Path,
    tmp_path: Path,
) -> None:
    receipt = execute_exported_candidate(
        candidate_repo,
        "HEAD",
        command=[
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'\\xff\\x00'); sys.stderr.buffer.write(b'\\xfe\\x01')",
        ],
        destination=tmp_path / "export-binary-output",
    )

    assert receipt.returncode == 0
    assert receipt.stdout == b"\xff\x00"
    assert receipt.stderr == b"\xfe\x01"
    assert receipt.stdout_sha256 == f"sha256:{hashlib.sha256(receipt.stdout).hexdigest()}"
    assert receipt.stderr_sha256 == f"sha256:{hashlib.sha256(receipt.stderr).hexdigest()}"


@pytest.mark.parametrize(
    "paths",
    [
        ["A.py", "a.py"],
        ["\u00e9.py", "e\u0301.py"],
        ["trailing-dot."],
        ["trailing-space "],
        ["CON"],
        ["nested/NUL.txt"],
        ["name:stream"],
        ["a//b.py"],
        ["a/./b.py"],
    ],
)
def test_export_rejects_platform_aliasing_paths(paths: list[str]) -> None:
    with pytest.raises(CandidateEvidenceError, match="alias|material|normalized|reserved"):
        validate_materializable_paths(paths)
