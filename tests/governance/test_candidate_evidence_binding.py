from __future__ import annotations

import ast
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

ROOT = Path(__file__).resolve().parents[2]


def _inside_sealed_windows_candidate() -> bool:
    return os.name == "nt" and os.environ.get("CRYODAQ_EXPORTED_CANDIDATE") == "1"


def _assert_active_export_binding() -> None:
    commit = os.environ["CRYODAQ_CANDIDATE_COMMIT"]
    tree = os.environ["CRYODAQ_CANDIDATE_TREE"]
    manifest_sha256 = os.environ["CRYODAQ_CANDIDATE_MANIFEST_SHA256"]
    assert len(commit) == 40 and all(character in "0123456789abcdef" for character in commit)
    assert len(tree) == 40 and all(character in "0123456789abcdef" for character in tree)
    assert len(manifest_sha256) == 71 and manifest_sha256.startswith("sha256:")
    assert all(character in "0123456789abcdef" for character in manifest_sha256.removeprefix("sha256:"))


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


def _assert_authority_refusal(stderr: bytes) -> None:
    assert any(
        marker in stderr
        for marker in (
            b"PermissionError",
            b"Read-only file system",
            b"Operation not permitted",
            b"WinError 5",
            b"CalledProcessError",
        )
    ), stderr.decode("utf-8", errors="replace")


def test_isolated_python_test_subprocesses_disable_bytecode() -> None:
    """Keep isolated Python children from writing into sealed candidates.

    Isolated mode deliberately ignores the ambient no-bytecode and pycache
    environment. Every literal test subprocess that requests -I must
    therefore also request -B itself.
    """

    offenders: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            arguments = [item.value for item in node.elts if isinstance(item, ast.Constant) and type(item.value) is str]
            if "-I" in arguments and "-B" not in arguments:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert offenders == [], f"isolated Python test subprocesses may write candidate bytecode: {offenders}"


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
    if _inside_sealed_windows_candidate():
        _assert_active_export_binding()
        return

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
    if _inside_sealed_windows_candidate():
        assert os.environ["PYTEST_ADDOPTS"] == "-p no:cacheprovider"
        assert "PYTEST_PLUGINS" not in os.environ
        assert "PYTHONHOME" not in os.environ
        assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
        assert os.environ["PYTHONNOUSERSITE"] == "1"
        assert os.environ["PYTHONUTF8"] == "1"
        assert os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        for key in (
            "CRYODAQ_CANDIDATE_PYTEST_BASETEMP",
            "CRYODAQ_STATE_ROOT",
            "PYTHONPYCACHEPREFIX",
            "XDG_CACHE_HOME",
        ):
            assert not Path(os.environ[key]).is_relative_to(ROOT)
        return

    _write(
        candidate_repo / "tests" / "test_environment.py",
        "import os\n"
        "from pathlib import Path\n\n"
        "def test_environment_is_sanitized() -> None:\n"
        "    assert os.environ['PYTEST_ADDOPTS'] == '-p no:cacheprovider'\n"
        "    assert 'PYTEST_PLUGINS' not in os.environ\n"
        "    assert 'PYTHONHOME' not in os.environ\n"
        "    assert os.environ['PYTHONDONTWRITEBYTECODE'] == '1'\n"
        "    assert os.environ['PYTHONNOUSERSITE'] == '1'\n"
        "    assert not Path(os.environ['PYTHONPYCACHEPREFIX']).is_relative_to(Path.cwd())\n"
        "    assert os.environ['PYTHONUTF8'] == '1'\n"
        "    assert os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'\n"
        "    assert not Path(os.environ['CRYODAQ_CANDIDATE_PYTEST_BASETEMP']).is_relative_to(Path.cwd())\n"
        "    assert not Path(os.environ['CRYODAQ_STATE_ROOT']).is_relative_to(Path.cwd())\n"
        "    assert not Path(os.environ['XDG_CACHE_HOME']).is_relative_to(Path.cwd())\n",
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
    pycache_root = tmp_path / ".export-sanitized-execution-state" / "pycache"
    runtime_root = tmp_path / ".export-sanitized-execution-state" / "runtime"
    assert pycache_root.is_dir()
    assert runtime_root.is_dir()
    assert not pycache_root.is_relative_to(receipt.export_root)
    assert not runtime_root.is_relative_to(receipt.export_root)
    assert not any(path.suffix == ".pyc" for path in receipt.export_root.rglob("*"))


def test_export_execution_redirects_nested_python_cache_outside_candidate(
    candidate_repo: Path,
    tmp_path: Path,
) -> None:
    if _inside_sealed_windows_candidate():
        before = {path for path in ROOT.rglob("*.pyc")}
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", "import pathlib"],
            capture_output=True,
            text=False,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert {path for path in ROOT.rglob("*.pyc")} == before
        assert not Path(os.environ["PYTHONPYCACHEPREFIX"]).is_relative_to(ROOT)
        return

    _write(candidate_repo / "src" / "pkg" / "nested.py", "VALUE = 42\n")
    commit = _commit(candidate_repo, "nested interpreter cache guard")
    script = (
        "import os, subprocess, sys; "
        "env={key: value for key, value in os.environ.items() "
        "if key in {'PATH','PYTHONPATH','PYTHONNOUSERSITE',"
        "'PYTHONPYCACHEPREFIX','PYTHONUTF8','SYSTEMROOT','WINDIR'}}; "
        "assert 'PYTHONDONTWRITEBYTECODE' not in env; "
        "raise SystemExit(subprocess.run([sys.executable,'-c','import pkg.nested'],env=env).returncode)"
    )
    receipt = execute_exported_candidate(
        candidate_repo,
        commit,
        command=[sys.executable, "-c", script],
        destination=tmp_path / "export-nested-cache",
    )

    assert receipt.returncode == 0, receipt.stdout + receipt.stderr
    assert not any(path.suffix == ".pyc" for path in receipt.export_root.rglob("*"))
    pycache_root = tmp_path / ".export-nested-cache-execution-state" / "pycache"
    assert pycache_root.is_dir()
    assert not pycache_root.is_relative_to(receipt.export_root)
    external_bytecode = tuple(pycache_root.rglob("*.pyc"))
    assert any(path.name.startswith("nested.") for path in external_bytecode)
    assert all(not path.is_relative_to(receipt.export_root) for path in external_bytecode)


def test_export_execution_rejects_committed_path_mutation(candidate_repo: Path, tmp_path: Path) -> None:
    receipt = execute_exported_candidate(
        candidate_repo,
        "HEAD",
        command=[
            sys.executable,
            "-c",
            "from pathlib import Path; "
            "path=Path('src/pkg/main.py'); original=path.read_bytes(); "
            "path.write_text('MUTATED\\n', encoding='utf-8'); "
            "exec(path.read_text(encoding='utf-8')); "
            "path.write_bytes(original); print('MUTATED_EXECUTED_RESTORED')",
        ],
        destination=tmp_path / "export-mutated",
    )

    assert receipt.returncode != 0
    assert b"MUTATED_EXECUTED_RESTORED" not in receipt.stdout
    _assert_authority_refusal(receipt.stderr)
    assert (receipt.export_root / "src" / "pkg" / "main.py").read_text(encoding="utf-8") == (
        candidate_repo / "src" / "pkg" / "main.py"
    ).read_text(encoding="utf-8")


def test_export_execution_rejects_chmod_mutate_execute_restore(candidate_repo: Path, tmp_path: Path) -> None:
    attack = """
import os, pathlib
p = pathlib.Path('src/pkg/main.py')
parents = [pathlib.Path('.'), pathlib.Path('src'), pathlib.Path('src/pkg')]
saved_dirs = [(d, d.stat().st_mode) for d in parents]
for d, _mode in saved_dirs:
    os.chmod(d, 0o755)
saved_file = p.stat().st_mode
os.chmod(p, 0o666)
original = p.read_bytes()
p.write_text("print('EXECUTED_MUTATED_BYTES')\\n", encoding='utf-8')
exec(compile(p.read_text(encoding='utf-8'), str(p), 'exec'))
p.write_bytes(original)
os.chmod(p, saved_file)
for d, mode in reversed(saved_dirs):
    os.chmod(d, mode)
print('CHMOD_BYPASS_COMPLETED')
"""
    receipt = execute_exported_candidate(
        candidate_repo,
        "HEAD",
        command=[sys.executable, "-c", attack],
        destination=tmp_path / "export-chmod-restore",
    )

    assert receipt.returncode != 0
    assert b"EXECUTED_MUTATED_BYTES" not in receipt.stdout
    assert b"CHMOD_BYPASS_COMPLETED" not in receipt.stdout
    _assert_authority_refusal(receipt.stderr)


@pytest.mark.parametrize(
    ("name", "attack", "success_marker"),
    [
        (
            "delete-recreate",
            "from pathlib import Path; p=Path('src/pkg/main.py'); "
            "p.unlink(); p.write_text(\"print('DELETE_RECREATE_EXECUTED')\\n\"); "
            "exec(p.read_text()); print('DELETE_RECREATE_COMPLETED')",
            b"DELETE_RECREATE_COMPLETED",
        ),
        (
            "rename-replace",
            "import os; from pathlib import Path; "
            "replacement=Path(os.environ['CRYODAQ_STATE_ROOT'])/'replacement.py'; "
            "replacement.write_text(\"print('RENAME_REPLACEMENT_EXECUTED')\\n\"); "
            "replacement.replace('src/pkg/main.py'); "
            "exec(Path('src/pkg/main.py').read_text()); print('RENAME_REPLACE_COMPLETED')",
            b"RENAME_REPLACE_COMPLETED",
        ),
        (
            "subprocess-chmod",
            'import subprocess, sys; code="import os; from pathlib import Path; '
            "p=Path('src/pkg/main.py'); os.chmod(p,0o666); "
            "p.write_bytes(b'MUTATED'); print('SUBPROCESS_CHMOD_COMPLETED')\"; "
            "raise SystemExit(subprocess.run([sys.executable,'-I','-B','-c',code]).returncode)",
            b"SUBPROCESS_CHMOD_COMPLETED",
        ),
        (
            "directory-chmod",
            "import os; from pathlib import Path; p=Path('src/pkg'); os.chmod(p,0o777); "
            "Path('src/pkg/added.py').write_text(\"print('DIRECTORY_MUTATION_EXECUTED')\\n\"); "
            "print('DIRECTORY_CHMOD_COMPLETED')",
            b"DIRECTORY_CHMOD_COMPLETED",
        ),
        (
            "hardlink-write",
            "import os; from pathlib import Path; "
            "link=Path(os.environ['CRYODAQ_STATE_ROOT'])/'linked.py'; "
            "os.link('src/pkg/main.py', link); link.write_bytes(b'MUTATED'); "
            "print('HARDLINK_WRITE_COMPLETED')",
            b"HARDLINK_WRITE_COMPLETED",
        ),
    ],
)
def test_export_execution_rejects_authority_bypass_attacks(
    candidate_repo: Path,
    tmp_path: Path,
    name: str,
    attack: str,
    success_marker: bytes,
) -> None:
    receipt = execute_exported_candidate(
        candidate_repo,
        "HEAD",
        command=[sys.executable, "-c", attack],
        destination=tmp_path / f"export-{name}",
    )

    assert receipt.returncode != 0
    assert success_marker not in receipt.stdout
    _assert_authority_refusal(receipt.stderr)


def test_active_export_refuses_full_authority_attack_battery() -> None:
    if os.environ.get("CRYODAQ_EXPORTED_CANDIDATE") != "1":
        pytest.skip("requires the real top-level sealed export")

    attacks: list[tuple[str, str, bytes]] = [
        (
            "chmod-restore",
            "import os; from pathlib import Path; p=Path('src/cryodaq/__init__.py'); "
            "mode=p.stat().st_mode; os.chmod(p,0o666); original=p.read_bytes(); "
            "p.write_text(\"print('EXECUTED_MUTATED_BYTES')\\n\"); exec(p.read_text()); p.write_bytes(original); "
            "os.chmod(p,mode); print('CHMOD_RESTORE_COMPLETED')",
            b"CHMOD_RESTORE_COMPLETED",
        ),
        (
            "delete-recreate",
            "from pathlib import Path; p=Path('src/cryodaq/__init__.py'); "
            "p.unlink(); p.write_bytes(b'MUTATED'); print('DELETE_RECREATE_COMPLETED')",
            b"DELETE_RECREATE_COMPLETED",
        ),
        (
            "rename-replace",
            "import os; from pathlib import Path; p=Path('src/cryodaq/__init__.py'); "
            "replacement=Path(os.environ['CRYODAQ_STATE_ROOT'])/'attack-replacement.py'; "
            "replacement.write_bytes(b'MUTATED'); replacement.replace(p); print('RENAME_REPLACE_COMPLETED')",
            b"RENAME_REPLACE_COMPLETED",
        ),
        (
            "hardlink",
            "import os; from pathlib import Path; p=Path('src/cryodaq/__init__.py'); "
            "link=Path(os.environ['CRYODAQ_STATE_ROOT'])/'attack-hardlink.py'; "
            "os.link(p,link); link.write_bytes(b'MUTATED'); print('HARDLINK_COMPLETED')",
            b"HARDLINK_COMPLETED",
        ),
        (
            "subprocess-chmod",
            'import subprocess,sys; code="import os; from pathlib import Path; '
            "p=Path('src/cryodaq/__init__.py'); os.chmod(p,0o666); "
            "p.write_bytes(b'MUTATED'); print('SUBPROCESS_CHMOD_COMPLETED')\"; "
            "raise SystemExit(subprocess.run([sys.executable,'-c',code]).returncode)",
            b"SUBPROCESS_CHMOD_COMPLETED",
        ),
        (
            "isolated-flags",
            'import subprocess,sys; code="from pathlib import Path; '
            "Path('src/cryodaq/__init__.py').write_bytes(b'MUTATED'); "
            "print('ISOLATED_FLAGS_COMPLETED')\"; "
            "raise SystemExit(subprocess.run([sys.executable,'-I','-B','-c',code]).returncode)",
            b"ISOLATED_FLAGS_COMPLETED",
        ),
        (
            "launcher-mutation",
            "import os; from pathlib import Path; p=Path(os.environ['CRYODAQ_CANDIDATE_SANDBOX_LAUNCHER']); "
            "p.write_bytes(b'MUTATED'); print('LAUNCHER_MUTATION_COMPLETED')",
            b"LAUNCHER_MUTATION_COMPLETED",
        ),
    ]
    if os.name == "nt":
        attacks.append(
            (
                "acl-rewrite",
                "import os,subprocess; from pathlib import Path; p=Path('src/cryodaq/__init__.py'); "
                "subprocess.run(['icacls.exe',str(p),'/grant',os.environ['USERNAME']+':F'],check=True); "
                "p.write_bytes(b'MUTATED'); print('ACL_REWRITE_COMPLETED')",
                b"ACL_REWRITE_COMPLETED",
            )
        )
    else:
        attacks.extend(
            [
                (
                    "original-path",
                    "import os; from pathlib import Path; "
                    "root=Path(os.environ['CRYODAQ_CANDIDATE_ORIGINAL_EXPORT_ROOT']); "
                    "(root/'src/cryodaq/__init__.py').write_bytes(b'MUTATED'); "
                    "print('ORIGINAL_PATH_COMPLETED')",
                    b"ORIGINAL_PATH_COMPLETED",
                ),
                (
                    "remount",
                    "import ctypes,os; from pathlib import Path; libc=ctypes.CDLL(None,use_errno=True); "
                    "libc.mount.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_char_p,"
                    "ctypes.c_ulong,ctypes.c_void_p]; result=libc.mount(None,b'.',None,0x1020,None); "
                    "result and (_ for _ in ()).throw(OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))); "
                    "Path('src/cryodaq/__init__.py').write_bytes(b'MUTATED'); print('REMOUNT_COMPLETED')",
                    b"REMOUNT_COMPLETED",
                ),
                (
                    "nested-user-mount-namespace",
                    "import ctypes,os; from pathlib import Path; libc=ctypes.CDLL(None,use_errno=True); "
                    "libc.unshare.argtypes=[ctypes.c_int]; libc.mount.argtypes=[ctypes.c_char_p,"
                    "ctypes.c_char_p,ctypes.c_char_p,ctypes.c_ulong,ctypes.c_void_p]; "
                    "result=libc.unshare(0x10000000|0x00020000); "
                    "result and (_ for _ in ()).throw(OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))); "
                    "result=libc.mount(None,b'.',None,0x1020,None); "
                    "result and (_ for _ in ()).throw(OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))); "
                    "Path('src/cryodaq/__init__.py').write_bytes(b'MUTATED'); "
                    "print('NESTED_NAMESPACE_COMPLETED')",
                    b"NESTED_NAMESPACE_COMPLETED",
                ),
                (
                    "proc-root",
                    "import os; from pathlib import Path; "
                    "original=Path(os.environ['CRYODAQ_CANDIDATE_ORIGINAL_EXPORT_ROOT']); "
                    "through_proc=Path(f'/proc/{os.getppid()}/root')/str(original).lstrip('/'); "
                    "(through_proc/'src/cryodaq/__init__.py').write_bytes(b'MUTATED'); "
                    "print('PROC_ROOT_COMPLETED')",
                    b"PROC_ROOT_COMPLETED",
                ),
            ]
        )

    for name, attack, success_marker in attacks:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", attack],
            cwd=ROOT,
            capture_output=True,
            text=False,
            check=False,
        )
        assert completed.returncode != 0, name
        assert success_marker not in completed.stdout, name
        assert b"EXECUTED_MUTATED_BYTES" not in completed.stdout, name
        _assert_authority_refusal(completed.stderr)


def test_export_execution_allows_honest_read_only_candidate(candidate_repo: Path, tmp_path: Path) -> None:
    if _inside_sealed_windows_candidate():
        _assert_active_export_binding()
        assert (ROOT / "src" / "cryodaq" / "__init__.py").is_file()
        return

    receipt = execute_exported_candidate(
        candidate_repo,
        "HEAD",
        command=[
            sys.executable,
            "-c",
            "from pathlib import Path; "
            "assert 'from pkg.dep import VALUE' in Path('src/pkg/main.py').read_text(encoding='utf-8'); "
            "print('HONEST_CANDIDATE_PASSED')",
        ],
        destination=tmp_path / "export-honest",
    )

    assert receipt.returncode == 0, receipt.stdout + receipt.stderr
    assert receipt.stdout.strip() == b"HONEST_CANDIDATE_PASSED"


def test_export_execution_keeps_state_copies_writable(candidate_repo: Path, tmp_path: Path) -> None:
    if _inside_sealed_windows_candidate():
        copied = Path(os.environ["CRYODAQ_STATE_ROOT"]) / "test-state-copy.py"
        shutil_source = ROOT / "src" / "cryodaq" / "__init__.py"
        import shutil

        shutil.copy2(shutil_source, copied)
        try:
            copied.write_text("STATE_COPY_WRITABLE\n", encoding="utf-8")
            assert copied.read_text(encoding="utf-8") == "STATE_COPY_WRITABLE\n"
        finally:
            copied.unlink(missing_ok=True)
        return

    receipt = execute_exported_candidate(
        candidate_repo,
        "HEAD",
        command=[
            sys.executable,
            "-c",
            "import os, shutil; from pathlib import Path; "
            "copy=Path(os.environ['CRYODAQ_STATE_ROOT'])/'copied-main.py'; "
            "shutil.copy2('src/pkg/main.py', copy); "
            "copy.write_text(\"print('STATE_COPY_WRITABLE')\\n\", encoding='utf-8'); "
            "print('STATE_COPY_WRITABLE')",
        ],
        destination=tmp_path / "export-state-copy",
    )

    assert receipt.returncode == 0, receipt.stdout + receipt.stderr
    assert receipt.stdout.strip() == b"STATE_COPY_WRITABLE"


def test_export_execution_rejects_unexpected_file_creation(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    if os.environ.get("CRYODAQ_EXPORTED_CANDIDATE") == "1":
        for name in ("unexpected.txt", "unexpected.pyc"):
            path = ROOT / name
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(path)!r}).write_bytes(b'not candidate')",
                ],
                capture_output=True,
                text=False,
                check=False,
            )
            assert completed.returncode != 0
            _assert_authority_refusal(completed.stderr)
            assert not path.exists()
        return

    candidate_repo = request.getfixturevalue("candidate_repo")
    for name in ("unexpected.txt", "unexpected.pyc"):
        receipt = execute_exported_candidate(
            candidate_repo,
            "HEAD",
            command=[
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({name!r}).write_bytes(b'not candidate')",
            ],
            destination=tmp_path / f"export-{name}",
        )
        assert receipt.returncode != 0
        _assert_authority_refusal(receipt.stderr)
        assert not (receipt.export_root / name).exists()


def test_export_execution_preserves_logical_git_modes_on_windows(candidate_repo: Path, tmp_path: Path) -> None:
    if _inside_sealed_windows_candidate():
        _assert_active_export_binding()
        return

    _write(candidate_repo / "scripts" / "tool.bat", "@echo off\n")
    _write(candidate_repo / "scripts" / "tool.sh", "#!/bin/sh\n")
    _run("git", "add", "-A", cwd=candidate_repo)
    _run("git", "update-index", "--chmod=+x", "scripts/tool.sh", cwd=candidate_repo)
    _run("git", "commit", "-m", "mode fixtures", cwd=candidate_repo)

    receipt = execute_exported_candidate(
        candidate_repo,
        "HEAD",
        command=[sys.executable, "-c", "print('unchanged')"],
        destination=tmp_path / "export-modes",
    )

    records = {record.path: record.mode for record in receipt.manifest.records}
    assert records["scripts/tool.bat"] == "100644"
    assert records["scripts/tool.sh"] == "100755"


def test_receipt_hashes_exact_output_bytes_without_unicode_replacement(
    candidate_repo: Path,
    tmp_path: Path,
) -> None:
    if _inside_sealed_windows_candidate():
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'\\xff\\x00'); sys.stderr.buffer.write(b'\\xfe\\x01')",
            ],
            capture_output=True,
            text=False,
            check=False,
        )
        assert completed.returncode == 0
        assert completed.stdout == b"\xff\x00"
        assert completed.stderr == b"\xfe\x01"
        return

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
    assert receipt.stderr.endswith(b"\xfe\x01")
    assert b"candidate-sandbox-preflight " in receipt.stderr[:-2]
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
