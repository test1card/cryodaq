from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools import unguarded_production_files as subject


def _git(repository: Path, *args: str) -> str:
    run = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return run.stdout.strip()


def _repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "guard@example.invalid")
    _git(path, "config", "user.name", "Guard Test")
    return path


def test_base_content_preserves_non_utf8_blob_bytes(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    source = repository / "src" / "latin1.py"
    source.parent.mkdir()
    expected = b"# coding: latin-1\nlabel = '\xe9'\n"
    source.write_bytes(expected)
    _git(repository, "add", "src/latin1.py")
    _git(repository, "commit", "-qm", "latin-1 base")
    head = _git(repository, "rev-parse", "HEAD")

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "_ROOT", repository, raising=False)

    assert subject.base_content(head, "src/latin1.py") == expected


def test_repository_root_is_stable_when_invoked_from_a_subdirectory(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    nested = repository / "tools" / "nested"
    nested.mkdir(parents=True)

    monkeypatch.chdir(nested)

    assert subject.repository_root().resolve() == repository.resolve()


def test_restore_path_never_chmods_through_a_symlink(tmp_path: Path, monkeypatch) -> None:
    restored = tmp_path / "link.py"
    chmod_calls: list[tuple[Path, int, bool]] = []

    monkeypatch.setattr(subject.os, "symlink", lambda _target, _path: None)

    def chmod(path: Path, mode: int, *, follow_symlinks: bool = True) -> None:
        chmod_calls.append((path, mode, follow_symlinks))

    monkeypatch.setattr(subject.os, "chmod", chmod)

    subject.restore_path(restored, subject.PathIdentity("symlink", "target.py", 0o777))

    assert chmod_calls == [(restored, 0o777, False)]


def test_existing_tree_entry_with_unreadable_blob_is_not_treated_as_absent(monkeypatch) -> None:
    object_id = "0" * 40

    def unreadable(args: list[str]) -> subprocess.CompletedProcess[bytes]:
        if args[0] == "ls-tree":
            tree_entry = f"100644 blob {object_id}\tsrc/unreadable.py\0".encode()
            return subprocess.CompletedProcess(args, 0, tree_entry, b"")
        if args[:2] == ["cat-file", "-e"]:
            return subprocess.CompletedProcess(args, 1, b"", b"missing blob")
        raise AssertionError(args)

    monkeypatch.setattr(subject, "_git_bytes", unreadable)

    with pytest.raises(subject.MeasurementError, match="tree entry.*no readable blob"):
        subject.git_entry("0123456789abcdef", "src/unreadable.py")


def test_main_reverts_a_rename_as_one_source_destination_mutation(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / "src" / "old_name.py"
    new = repository / "src" / "new_name.py"
    old.parent.mkdir()
    old.write_bytes(b"VALUE = 'guarded'\n")
    _git(repository, "add", "src/old_name.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "src/old_name.py", "src/new_name.py")
    _git(repository, "commit", "-qm", "rename production module")

    observed: list[tuple[bool, bool]] = []

    def observe_pair(_suites: list[str], _cache: Path) -> list[str]:
        state = (old.exists(), new.exists())
        observed.append(state)
        return [] if state in {(False, True), (True, False)} else ["test_imports_production_module"]

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", observe_pair)
    monkeypatch.setattr(
        sys,
        "argv",
        ["unguarded_production_files", "--base", base, "--suite", "tests"],
    )

    assert subject.main() == 1  # the correct rename revert is intentionally unguarded
    assert observed == [(False, True), (True, False)]
    assert not old.exists()
    assert new.read_text(encoding="utf-8") == "VALUE = 'guarded'\n"


def test_main_restores_rename_when_old_parent_is_absent(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    old = repository / "src" / "oldpkg" / "mod.py"
    new = repository / "src" / "mod.py"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"VALUE = 'guarded'\n")
    _git(repository, "add", "src/oldpkg/mod.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "src/oldpkg/mod.py", "src/mod.py")
    old.parent.rmdir()
    _git(repository, "commit", "-qm", "rename out of removed directory")

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", lambda _suites, _cache: [])
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 1
    assert not old.exists()
    assert new.read_bytes() == b"VALUE = 'guarded'\n"


def test_main_never_skips_a_mode_only_production_change_as_identical(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    source = repository / "src" / "entrypoint.py"
    source.parent.mkdir()
    source.write_bytes(b"print('operator entry point')\n")
    _git(repository, "add", "src/entrypoint.py")
    _git(repository, "commit", "-qm", "non-executable base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "update-index", "--chmod=+x", "src/entrypoint.py")
    _git(repository, "commit", "-qm", "make entry point executable")
    _git(repository, "config", "core.filemode", "false")

    runs = 0

    def green(_suites: list[str], _cache: Path) -> list[str]:
        nonlocal runs
        runs += 1
        return []

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", green)
    monkeypatch.setattr(
        sys,
        "argv",
        ["unguarded_production_files", "--base", base, "--suite", "tests"],
    )

    assert subject.main() == 1
    output = capsys.readouterr().out
    assert "identical to the merge base" not in output
    assert runs == 2 or "NOT MEASURED" in output


@pytest.mark.parametrize("drift", ["suite_input", "head"])
def test_main_refuses_drift_after_the_green_control(tmp_path: Path, monkeypatch, capsys, drift: str) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    source = repository / "src" / "production.py"
    suite_input = repository / "tests" / "test_guard.py"
    source.parent.mkdir()
    suite_input.parent.mkdir()
    source.write_bytes(b"VALUE = 'base'\n")
    suite_input.write_bytes(b"def test_guard(): pass\n")
    _git(repository, "add", "src/production.py", "tests/test_guard.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    source.write_bytes(b"VALUE = 'candidate'\n")
    _git(repository, "commit", "-qam", "candidate")

    runs = 0

    def drift_after_control(_suites: list[str], _cache: Path) -> list[str]:
        nonlocal runs
        runs += 1
        if runs == 1:
            if drift == "suite_input":
                suite_input.write_bytes(b"def test_guard(): assert False\n")
            else:
                _git(repository, "commit", "--allow-empty", "-qm", "concurrent head")
            return []
        return ["test_guard"]

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", drift_after_control)
    monkeypatch.setattr(
        sys,
        "argv",
        ["unguarded_production_files", "--base", base, "--suite", "tests"],
    )

    assert subject.main() == 2
    assert runs == 1
    assert source.read_bytes() == b"VALUE = 'candidate'\n"
    assert "suite inputs drifted after the green control" in capsys.readouterr().out


def test_main_refuses_suite_input_drift_before_accepting_a_mutant_result(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    source = repository / "src" / "production.py"
    suite_input = repository / "tests" / "test_guard.py"
    source.parent.mkdir()
    suite_input.parent.mkdir()
    source.write_bytes(b"VALUE = 'base'\n")
    suite_input.write_bytes(b"def test_guard(): pass\n")
    _git(repository, "add", "src/production.py", "tests/test_guard.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    source.write_bytes(b"VALUE = 'candidate'\n")
    _git(repository, "commit", "-qam", "candidate")

    runs = 0

    def drift_during_mutant(_suites: list[str], _cache: Path) -> list[str]:
        nonlocal runs
        runs += 1
        if runs == 1:
            return []
        suite_input.write_bytes(b"def test_guard(): assert False\n")
        return ["test_guard"]

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", drift_during_mutant)
    monkeypatch.setattr(
        sys,
        "argv",
        ["unguarded_production_files", "--base", base, "--suite", "tests"],
    )

    assert subject.main() == 2
    assert runs == 2
    assert source.read_bytes() == b"VALUE = 'candidate'\n"
    assert "suite inputs drifted before mutation attribution" in capsys.readouterr().out


def test_main_refuses_stable_uncommitted_suite_inputs(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    source = repository / "src" / "production.py"
    source.parent.mkdir()
    source.write_bytes(b"VALUE = 'base'\n")
    _git(repository, "add", "src/production.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    source.write_bytes(b"VALUE = 'candidate'\n")
    _git(repository, "commit", "-qam", "candidate")
    suite_input = repository / "tests" / "test_guard.py"
    suite_input.parent.mkdir()
    suite_input.write_bytes(b"def test_guard(): pass\n")

    runs = 0

    def covered_only_by_untracked_test(_suites: list[str], _cache: Path) -> list[str]:
        nonlocal runs
        runs += 1
        return [] if source.read_bytes() == b"VALUE = 'candidate'\n" else ["test_guard"]

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", covered_only_by_untracked_test)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 2
    assert runs == 0
    assert "uncommitted candidate inputs" in capsys.readouterr().out


def test_main_refuses_to_certify_multiple_independent_hunks_as_one(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    source = repository / "src" / "production.py"
    source.parent.mkdir()
    source.write_bytes(b"GUARDED = 'base'\n\n# unrelated area\n\nUNGUARDED = 'base'\n")
    _git(repository, "add", "src/production.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    source.write_bytes(b"GUARDED = 'candidate'\n\n# unrelated area\n\nUNGUARDED = 'candidate'\n")
    _git(repository, "commit", "-qam", "two independent production edits")

    runs = 0

    def only_first_edit_is_guarded(_suites: list[str], _cache: Path) -> list[str]:
        nonlocal runs
        runs += 1
        return [] if "GUARDED = 'candidate'" in source.read_text(encoding="utf-8") else ["test_guarded"]

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", only_first_edit_is_guarded)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 1
    assert runs == 1
    assert "multiple independent diff hunks" in capsys.readouterr().out
