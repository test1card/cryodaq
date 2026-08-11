from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
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


def test_repository_root_falls_back_to_candidate_marker(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "candidate"
    (repository / "tools").mkdir(parents=True)
    (repository / "src").mkdir()
    (repository / "tools" / "unguarded_production_files.py").write_text("", encoding="utf-8")

    def missing_git(args: list[str], env=None):
        return subprocess.CompletedProcess(args, 128, "", "not a git repository")

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "_run", missing_git)

    assert subject.repository_root() == repository


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
    assert observed == [(False, True), (True, False), (True, False)]
    assert not old.exists()
    assert new.read_text(encoding="utf-8") == "VALUE = 'guarded'\n"


def test_main_refuses_rename_when_old_parent_is_absent(tmp_path: Path, monkeypatch, capsys) -> None:
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
    runs = 0

    def green(_suites: list[str], _cache: Path) -> list[str]:
        nonlocal runs
        runs += 1
        return []

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", green)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 1
    assert runs == 1
    assert not old.parent.exists()
    assert not old.exists()
    assert new.read_bytes() == b"VALUE = 'guarded'\n"
    assert "rename source parent is absent" in capsys.readouterr().out


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
    assert runs == 3 or "NOT MEASURED" in output


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
    old = repository / "src" / "production_old.py"
    new = repository / "src" / "production.py"
    suite_input = repository / "tests" / "test_guard.py"
    old.parent.mkdir()
    suite_input.parent.mkdir()
    old.write_bytes(b"VALUE = 'candidate'\n")
    suite_input.write_bytes(b"def test_guard(): pass\n")
    _git(repository, "add", "src/production_old.py", "tests/test_guard.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "src/production_old.py", "src/production.py")
    _git(repository, "commit", "-qm", "candidate rename")

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
    assert runs == 3
    assert not old.exists()
    assert new.read_bytes() == b"VALUE = 'candidate'\n"
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


def test_main_refuses_to_certify_multiple_independent_edits_as_one(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    source = repository / "src" / "production.py"
    source.parent.mkdir()
    source.write_bytes(b"GUARDED = 'base'\nUNGUARDED = 'base'\n")
    _git(repository, "add", "src/production.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    source.write_bytes(b"GUARDED = 'candidate'\nUNGUARDED = 'candidate'\n")
    _git(repository, "commit", "-qam", "two adjacent independent production edits")

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
    assert "content changes may contain multiple independent edits" in capsys.readouterr().out


def test_main_refuses_to_certify_an_added_multi_behavior_artifact(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    marker = repository / "README"
    marker.write_text("base\n", encoding="utf-8")
    _git(repository, "add", "README")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    source = repository / "src" / "production.py"
    source.parent.mkdir()
    source.write_bytes(b"GUARDED = True\nUNGUARDED = True\n")
    _git(repository, "add", "src/production.py")
    _git(repository, "commit", "-qm", "add two production behaviors")
    runs = 0

    def green(_suites: list[str], _cache: Path) -> list[str]:
        nonlocal runs
        runs += 1
        return []

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", green)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 1
    assert runs == 1
    assert source.read_bytes() == b"GUARDED = True\nUNGUARDED = True\n"
    assert "content changes may contain multiple independent edits" in capsys.readouterr().out


def test_runtime_artifact_without_source_suffix_is_selected(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    base_file = repository / "src" / "cryodaq" / "web" / "static" / "index.html"
    base_file.parent.mkdir(parents=True)
    base_file.write_bytes(b"<html>base</html>\n")
    _git(repository, "add", "src/cryodaq/web/static/index.html")
    _git(repository, "commit", "-qm", "base dashboard")
    base = _git(repository, "rev-parse", "HEAD")
    base_file.write_bytes(b"<html>candidate</html>\n")
    _git(repository, "add", "src/cryodaq/web/static/index.html")
    _git(repository, "commit", "-qm", "change dashboard")

    monkeypatch.chdir(repository)
    includes = subject.default_runtime_includes(base, "HEAD")
    selected = subject.changed_files(base, includes, subject._DEFAULT_SUFFIXES)

    assert [artifact.label for artifact in selected] == ["src/cryodaq/web/static/index.html"]


def test_failures_keep_distinct_full_node_ids_for_identical_messages(monkeypatch, tmp_path: Path) -> None:
    output = "\n".join(
        [
            "FAILED tests/a.py::test_guard - AssertionError: same",
            "FAILED tests/b.py::test_guard - AssertionError: same",
        ]
    )
    monkeypatch.setattr(
        subject,
        "_run_candidate_process",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, output, ""),
    )

    assert subject.failures(["tests"], tmp_path / "cache") == [
        "tests/a.py::test_guard",
        "tests/b.py::test_guard",
    ]


def test_default_roster_derives_a_new_runtime_root_from_git_trees(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    marker = repository / "README"
    marker.write_text("base\n", encoding="utf-8")
    _git(repository, "add", "README")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    runtime_path = "firmware/controller.lua"
    source = repository / runtime_path
    source.parent.mkdir()
    source.write_text("VALUE = 'candidate'\n", encoding="utf-8")
    _git(repository, "add", runtime_path)
    _git(repository, "commit", "-qm", "add a new runtime root")
    monkeypatch.chdir(repository)

    includes = subject.default_runtime_includes(base, "HEAD")
    selected = {
        path for artifact in subject.changed_files(base, includes, subject._DEFAULT_SUFFIXES) for path in artifact.paths
    }
    assert "firmware/" in includes
    assert runtime_path in selected

    without_new_root = tuple(root for root in includes if root != "firmware/")
    without_paths = {
        path
        for artifact in subject.changed_files(base, without_new_root, subject._DEFAULT_SUFFIXES)
        for path in artifact.paths
    }
    assert runtime_path not in without_paths


def test_main_filters_are_additive_and_reconfirm_mutant_red_then_candidate_green(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / "firmware" / "watchdog.lua"
    new = repository / "firmware" / "watchdog_v2.lua"
    old.parent.mkdir()
    old.write_text("VALUE = 'guarded'\n", encoding="utf-8")
    _git(repository, "add", "firmware/watchdog.lua")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "firmware/watchdog.lua", "firmware/watchdog_v2.lua")
    _git(repository, "commit", "-qm", "rename runtime watchdog")
    observed: list[tuple[bool, bool]] = []

    def guard(_suites: list[str], _cache: Path) -> list[str]:
        state = (old.exists(), new.exists())
        observed.append(state)
        return [] if state == (False, True) else ["test_runtime_guard"]

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", guard)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "unguarded_production_files",
            "--base",
            base,
            "--suite",
            "tests",
            "--include",
            "src/",
            "--suffix",
            ".py",
        ],
    )

    assert subject.main() == 0
    assert observed == [(False, True), (True, False), (True, False), (False, True)]
    assert "firmware/watchdog.lua -> firmware/watchdog_v2.lua" in capsys.readouterr().out


def test_main_does_not_certify_a_failure_that_remains_red_after_restore(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / "src" / "production_old.py"
    new = repository / "src" / "production.py"
    old.parent.mkdir()
    old.write_text("VALUE = 'guarded'\n", encoding="utf-8")
    _git(repository, "add", "src/production_old.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "src/production_old.py", "src/production.py")
    _git(repository, "commit", "-qm", "candidate rename")
    results = iter(([], ["test_timing_sensitive"], ["test_timing_sensitive"], ["test_timing_sensitive"]))

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", lambda _suites, _cache: next(results))
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 1
    assert not old.exists()
    assert new.read_text(encoding="utf-8") == "VALUE = 'guarded'\n"
    assert "restored candidate was not green" in capsys.readouterr().out


def test_failures_times_out_a_hanging_pytest_process(tmp_path: Path, monkeypatch) -> None:
    hanging = tmp_path / "test_hangs.py"
    hanging.write_text("import time\n\ndef test_hangs():\n    time.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(subject, "_PYTEST_TIMEOUT_SECONDS", 0.2)

    with pytest.raises(subject.MeasurementError, match="exceeded 0.2 seconds"):
        subject.failures([str(hanging)], tmp_path / "cache")


def test_failures_settles_the_entire_pytest_process_tree_on_timeout(tmp_path: Path, monkeypatch) -> None:
    pid_path = tmp_path / "pytest-grandchild.pid"
    hanging = tmp_path / "test_process_tree.py"
    hanging.write_text(
        "import pathlib, subprocess, sys, time\n\n"
        "def test_hangs_after_spawning_a_child():\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"    pathlib.Path({str(pid_path)!r}).write_text(str(child.pid), encoding='ascii')\n"
        "    time.sleep(60)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(subject, "_PYTEST_TIMEOUT_SECONDS", 10.0)

    with pytest.raises(subject.MeasurementError, match="exceeded 10.0 seconds"):
        subject.failures([str(hanging)], tmp_path / "cache")

    assert pid_path.exists(), "the real pytest test did not reach its child-process boundary"
    grandchild_pid = int(pid_path.read_text(encoding="ascii"))
    deadline = time.monotonic() + 1.0
    while psutil.pid_exists(grandchild_pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    survived = psutil.pid_exists(grandchild_pid)
    if survived:
        process = psutil.Process(grandchild_pid)
        process.kill()
        process.wait(timeout=5)
    assert not survived, "pytest grandchild survived the measurement timeout"


def test_next_main_invocation_recovers_an_interrupted_mutation(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    source = repository / "src" / "production.py"
    source.parent.mkdir()
    source.write_text("VALUE = 'base'\n", encoding="utf-8")
    _git(repository, "add", "src/production.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    source.write_text("VALUE = 'candidate'\n", encoding="utf-8")
    _git(repository, "commit", "-qam", "candidate")
    monkeypatch.chdir(repository)
    original = subject.path_identity(source)
    mutant = subject.git_entry(base, "src/production.py")
    subject.arm_recovery(repository, (("src/production.py", original, mutant),))
    journal = subject._recovery_path(repository)
    assert journal.exists()
    assert not journal.resolve().is_relative_to(repository.resolve())
    assert os.stat(journal).st_dev == os.stat(repository).st_dev
    assert not (repository / subject._RECOVERY_NAME).exists()
    assert mutant is not None
    subject.materialize_git_entry(repository, source, mutant)

    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", "HEAD"])

    assert subject.main() == 0
    assert source.read_text(encoding="utf-8") == "VALUE = 'candidate'\n"
    assert not journal.exists()
    assert not (repository / subject._RECOVERY_NAME).exists()
    assert "recovered the candidate from an interrupted mutation" in capsys.readouterr().out


def test_recovery_never_overwrites_bytes_written_after_the_mutant(tmp_path: Path) -> None:
    repository = tmp_path / "candidate"
    repository.mkdir()
    source = repository / "src" / "production.py"
    source.parent.mkdir()
    source.write_text("VALUE = 'candidate'\n", encoding="utf-8")
    original = subject.path_identity(source)
    mutant = subject.GitEntry("100644", "blob", "0" * 40, b"VALUE = 'base'\n")
    subject.arm_recovery(repository, (("src/production.py", original, mutant),))
    source.write_text("VALUE = 'another writer'\n", encoding="utf-8")

    with pytest.raises(subject.MeasurementError, match="neither the recorded candidate nor mutant"):
        subject.recover_pending(repository)

    journal = subject._recovery_path(repository)
    assert source.read_text(encoding="utf-8") == "VALUE = 'another writer'\n"
    assert journal.exists()
    assert not journal.resolve().is_relative_to(repository.resolve())
    assert not (repository / subject._RECOVERY_NAME).exists()
    subject.clear_recovery(repository)


def test_recovery_journal_is_not_visible_to_the_measured_suite(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / "src" / "before.py"
    new = repository / "src" / "after.py"
    old.parent.mkdir()
    old.write_text("VALUE = 'guarded'\n", encoding="utf-8")
    _git(repository, "add", "src/before.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "src/before.py", "src/after.py")
    _git(repository, "commit", "-qm", "candidate rename")
    runs = 0

    def detect_checkout_journal(_suites: list[str], _cache: Path) -> list[str]:
        nonlocal runs
        runs += 1
        return ["test_checkout_has_no_measurement_state"] if (repository / subject._RECOVERY_NAME).exists() else []

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", detect_checkout_journal)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 1
    assert runs == 3
    assert not old.exists()
    assert new.read_text(encoding="utf-8") == "VALUE = 'guarded'\n"
    assert not (repository / subject._RECOVERY_NAME).exists()
    assert not subject._recovery_path(repository).exists()


def test_mutant_materialization_is_crash_atomic_and_external(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "candidate"
    target = repository / "src" / "production.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"CANDIDATE-CONTENT\n")
    entry = subject.GitEntry("100644", "blob", "0" * 40, b"BASE-CONTENT\n")
    staging_paths: list[Path] = []

    def interrupt_staging(staging: Path, staged_entry: subject.GitEntry) -> None:
        staging_paths.append(staging)
        assert not staging.resolve().is_relative_to(repository.resolve())
        assert os.stat(staging.parent).st_dev == os.stat(repository).st_dev
        staging.write_bytes(staged_entry.content[:5])
        raise RuntimeError("simulated interruption during mutant staging")

    monkeypatch.setattr(subject, "_materialize_git_entry", interrupt_staging)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        subject.materialize_git_entry(repository, target, entry)

    assert target.read_bytes() == b"CANDIDATE-CONTENT\n"
    assert len(staging_paths) == 1
    assert not staging_paths[0].exists()


def test_atomic_restore_replaces_only_from_complete_external_staging(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "candidate"
    target = repository / "src" / "production.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"MUTANT\n")
    original = subject.PathIdentity("file", b"CANDIDATE\n", 0o644)
    real_replace = subject.os.replace
    staging_paths: list[Path] = []

    def inspect_replace(staging: Path, destination: Path) -> None:
        staging = Path(staging)
        staging_paths.append(staging)
        assert destination == target
        assert staging.read_bytes() == b"CANDIDATE\n"
        assert not staging.resolve().is_relative_to(repository.resolve())
        assert os.stat(staging).st_dev == os.stat(repository).st_dev
        real_replace(staging, destination)

    monkeypatch.setattr(subject.os, "replace", inspect_replace)

    subject.restore_path_atomically(repository, target, original)

    assert target.read_bytes() == b"CANDIDATE\n"
    assert len(staging_paths) == 1
    assert not staging_paths[0].exists()


def test_unverified_process_tree_blocks_restore_and_automatic_recovery(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / "src" / "before.py"
    new = repository / "src" / "after.py"
    old.parent.mkdir()
    old.write_text("VALUE = 'guarded'\n", encoding="utf-8")
    _git(repository, "add", "src/before.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "src/before.py", "src/after.py")
    _git(repository, "commit", "-qm", "candidate rename")
    process_runs = 0

    def lose_settlement(command, **_kwargs):
        nonlocal process_runs
        process_runs += 1
        if process_runs == 1:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise subject.CandidateProcessUnsettledError("simulated unverified descendant")

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "_run_candidate_process", lose_settlement)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])
    journal = subject._recovery_path(repository)

    try:
        assert subject.main() == 2
        first_output = capsys.readouterr().out
        assert process_runs == 2
        assert old.read_text(encoding="utf-8") == "VALUE = 'guarded'\n"
        assert not new.exists()
        assert journal.exists()
        assert '"restore_blocked"' in journal.read_text(encoding="utf-8")
        assert "mutant and blocked recovery journal were left intact" in first_output

        monkeypatch.setattr(
            subject,
            "_run_candidate_process",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("blocked recovery must precede pytest")),
        )
        assert subject.main() == 2
        second_output = capsys.readouterr().out
        assert "automatic recovery is blocked after an unverified process tree" in second_output
        assert old.read_text(encoding="utf-8") == "VALUE = 'guarded'\n"
        assert not new.exists()
    finally:
        subject.clear_recovery(repository)
        old.unlink(missing_ok=True)
        new.write_text("VALUE = 'guarded'\n", encoding="utf-8")


def test_main_refuses_non_green_control_suite(tmp_path: Path, monkeypatch, capsys) -> None:
    repository = _repository(tmp_path / "candidate")
    source = repository / "src" / "production.py"
    source.parent.mkdir()
    source.write_bytes(b"VALUE = 'base'\n")
    _git(repository, "add", "src/production.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    source.write_bytes(b"VALUE = 'candidate'\n")
    _git(repository, "commit", "-qam", "candidate")

    calls = 0

    def green_control(_suites: list[str], _cache: Path) -> list[str]:
        nonlocal calls
        calls += 1
        return ["tests/test_guard.py::test_guard"]

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", green_control)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 2
    assert calls == 1
    assert "control run is not green" in capsys.readouterr().out


def test_failures_refuses_crashed_pytest_return_codes(monkeypatch, tmp_path: Path) -> None:
    suite = tmp_path / "tests" / "crashed.py"

    def crashed_pytest(command, root=None, **_kwargs) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 4, b"", b"internal error")

    monkeypatch.setattr(subject, "_run_candidate_process", crashed_pytest)
    monkeypatch.setattr(subject, "repository_root", lambda: tmp_path)

    with pytest.raises(subject.MeasurementError, match="exited 4 with no readable result"):
        subject.failures([str(suite)], tmp_path / "cache")


def test_failures_uses_a_fresh_pyc_cache_prefix_for_each_mutation_run(monkeypatch, tmp_path: Path) -> None:
    suite = ["tests"]
    captured: list[str] = []

    def capture_prefix(command, root=None, **kwargs) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs.get("environment", {})
        captured.append(environment.get("PYTHONPYCACHEPREFIX", ""))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subject, "_run_candidate_process", capture_prefix)
    monkeypatch.setattr(subject, "repository_root", lambda: tmp_path)

    assert subject.failures(suite, tmp_path / "first") == []
    assert subject.failures(suite, tmp_path / "second") == []
    assert len(captured) == 2
    assert captured[0] != ""
    assert captured[1] != ""
    assert captured[0] != captured[1]


def test_git_queries_strip_git_environment_from_repository_commands(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str | None] = {}

    def capture_run(args: list[str], env=None, timeout=None):
        captured.update(
            {key: (None if env is None else env.get(key)) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subject, "_run", capture_run)

    with monkeypatch.context() as m:
        m.setenv("GIT_DIR", str(tmp_path / "alt.git"))
        m.setenv("GIT_WORK_TREE", str(tmp_path / "work"))
        m.setenv("GIT_INDEX_FILE", str(tmp_path / "index"))
        subject._git(["status", "--porcelain"])

    assert captured["GIT_DIR"] is None
    assert captured["GIT_WORK_TREE"] is None
    assert captured["GIT_INDEX_FILE"] is None
