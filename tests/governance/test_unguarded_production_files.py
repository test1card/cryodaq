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
