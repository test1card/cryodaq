from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

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


@pytest.fixture(autouse=True)
def _disposable_state_is_test_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subject.tempfile, "tempdir", str(tmp_path))


def _candidate_rename(
    repository: Path,
    old_relative: str = "src/before.py",
    new_relative: str = "src/after.py",
) -> tuple[str, Path, Path]:
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / old_relative
    new = repository / new_relative
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"VALUE = 'guarded'\n")
    _git(repository, "add", old_relative)
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    new.parent.mkdir(parents=True, exist_ok=True)
    _git(repository, "mv", old_relative, new_relative)
    _git(repository, "commit", "-qm", "candidate rename")
    return base, old, new


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


def test_disposable_exact_rename_never_writes_the_source_checkout(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    base, old, new = _candidate_rename(repository)
    head = _git(repository, "rev-parse", "HEAD")
    monkeypatch.chdir(repository)
    before = subject.git_entry(base, "src/before.py")
    candidate = subject.git_entry(head, "src/after.py")
    assert before is not None and candidate is not None

    with subject.disposable_checkout(
        repository,
        head,
        reverse_rename=("src/before.py", "src/after.py", before, candidate),
    ) as checkout:
        assert (checkout / "src" / "before.py").read_bytes() == b"VALUE = 'guarded'\n"
        assert not (checkout / "src" / "after.py").exists()
        assert not old.exists()
        assert new.read_bytes() == b"VALUE = 'guarded'\n"

    assert not old.exists()
    assert new.read_bytes() == b"VALUE = 'guarded'\n"


def test_existing_tree_entry_with_unreadable_blob_is_not_treated_as_absent(monkeypatch) -> None:
    object_id = "0" * 40

    def unreadable(_root: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
        if args[0] == "ls-tree":
            tree_entry = f"100644 blob {object_id}\tsrc/unreadable.py\0".encode()
            return subprocess.CompletedProcess(args, 0, tree_entry, b"")
        if args[:2] == ["cat-file", "-e"]:
            return subprocess.CompletedProcess(args, 1, b"", b"missing blob")
        raise AssertionError(args)

    monkeypatch.setattr(subject, "_git_bytes_at", unreadable)

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

    def observe_pair(_suites: list[str], _cache: Path, **kwargs) -> list[str]:
        checkout = Path(kwargs["root"])
        state = ((checkout / "src" / "old_name.py").exists(), (checkout / "src" / "new_name.py").exists())
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


def test_main_isolates_rename_when_old_parent_is_absent(tmp_path: Path, monkeypatch, capsys) -> None:
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

    def green(_suites: list[str], _cache: Path, **_kwargs) -> list[str]:
        nonlocal runs
        runs += 1
        return []

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", green)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 1
    assert runs == 3
    assert not old.parent.exists()
    assert not old.exists()
    assert new.read_bytes() == b"VALUE = 'guarded'\n"
    assert "UNGUARDED AT THIS CHANGE'S OWN PURPOSE" in capsys.readouterr().out


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

    def green(_suites: list[str], _cache: Path, **_kwargs) -> list[str]:
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

    def drift_after_control(_suites: list[str], _cache: Path, **_kwargs) -> list[str]:
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
    assert "source inputs drifted after the green control" in capsys.readouterr().out


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

    def drift_during_mutant(_suites: list[str], _cache: Path, **_kwargs) -> list[str]:
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
    assert "suite inputs drifted during mutation attribution" in capsys.readouterr().out


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

    def covered_only_by_untracked_test(_suites: list[str], _cache: Path, **_kwargs) -> list[str]:
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

    def only_first_edit_is_guarded(_suites: list[str], _cache: Path, **_kwargs) -> list[str]:
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

    def green(_suites: list[str], _cache: Path, **_kwargs) -> list[str]:
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
    selected = {path for artifact in subject.changed_files(base, "HEAD", includes) for path in artifact.paths}
    assert "firmware/" in includes
    assert runtime_path in selected

    without_new_root = tuple(root for root in includes if root != "firmware/")
    without_paths = {
        path for artifact in subject.changed_files(base, "HEAD", without_new_root) for path in artifact.paths
    }
    assert runtime_path not in without_paths


def test_default_roster_derives_a_new_top_level_runtime_file(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    marker = repository / "README"
    marker.write_text("base\n", encoding="utf-8")
    _git(repository, "add", "README")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    runtime_path = "controller.lua"
    (repository / runtime_path).write_text("VALUE = 'candidate'\n", encoding="utf-8")
    _git(repository, "add", runtime_path)
    _git(repository, "commit", "-qm", "add top-level runtime code")
    monkeypatch.chdir(repository)

    includes = subject.default_runtime_includes(base, "HEAD")
    selected = {path for artifact in subject.changed_files(base, "HEAD", includes) for path in artifact.paths}
    assert runtime_path in includes
    assert runtime_path in selected

    without_file = tuple(root for root in includes if root != runtime_path)
    without_paths = {path for artifact in subject.changed_files(base, "HEAD", without_file) for path in artifact.paths}
    assert runtime_path not in without_paths


def test_main_filters_are_additive_and_reconfirm_mutant_red_then_candidate_green(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / "firmware" / "watchdog.lua"

    old.parent.mkdir()
    old.write_text("VALUE = 'guarded'\n", encoding="utf-8")
    _git(repository, "add", "firmware/watchdog.lua")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "firmware/watchdog.lua", "firmware/watchdog_v2.lua")
    _git(repository, "commit", "-qm", "rename runtime watchdog")
    observed: list[tuple[bool, bool]] = []

    def guard(_suites: list[str], _cache: Path, **kwargs) -> list[str]:
        checkout = Path(kwargs["root"])
        state = (
            (checkout / "firmware" / "watchdog.lua").exists(),
            (checkout / "firmware" / "watchdog_v2.lua").exists(),
        )
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
    monkeypatch.setattr(subject, "failures", lambda _suites, _cache, **_kwargs: next(results))
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 1
    assert not old.exists()
    assert new.read_text(encoding="utf-8") == "VALUE = 'guarded'\n"
    assert "fresh candidate confirmation was not green" in capsys.readouterr().out


def test_failures_times_out_a_hanging_pytest_process(tmp_path: Path, monkeypatch) -> None:
    checkout = _repository(tmp_path / "checkout")
    hanging = checkout / "tests" / "test_hangs.py"
    hanging.parent.mkdir()
    hanging.write_text("import time\n\ndef test_hangs():\n    time.sleep(60)\n", encoding="utf-8")
    _git(checkout, "add", "tests/test_hangs.py")
    _git(checkout, "commit", "-qm", "add hanging test")
    monkeypatch.setattr(subject, "_PYTEST_TIMEOUT_SECONDS", 0.2)

    with pytest.raises(subject.MeasurementError, match="exceeded 0.2 seconds"):
        subject.failures(["tests/test_hangs.py"], tmp_path / "run", root=checkout, source_root=checkout)


def test_failures_settles_the_entire_pytest_process_tree_on_timeout(tmp_path: Path, monkeypatch) -> None:
    checkout = _repository(tmp_path / "checkout")
    pid_path = checkout / "pytest-grandchild.pid"
    hanging = checkout / "tests" / "test_process_tree.py"
    hanging.parent.mkdir()
    hanging.write_text(
        "import pathlib, subprocess, sys, time\n\n"
        "def test_hangs_after_spawning_a_child():\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"    pathlib.Path({str(pid_path)!r}).write_text(str(child.pid), encoding='ascii')\n"
        "    time.sleep(60)\n",
        encoding="utf-8",
    )
    _git(checkout, "add", "tests/test_process_tree.py")
    _git(checkout, "commit", "-qm", "add process-tree test")
    monkeypatch.setattr(subject, "_PYTEST_TIMEOUT_SECONDS", 10.0)

    with pytest.raises(subject.MeasurementError, match="exceeded 10.0 seconds"):
        subject.failures(["tests/test_process_tree.py"], tmp_path / "run", root=checkout, source_root=checkout)

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


def test_disposable_state_is_external_same_volume_and_removed(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    base, old, new = _candidate_rename(repository)
    head = _git(repository, "rev-parse", "HEAD")
    monkeypatch.chdir(repository)
    before = subject.git_entry(base, "src/before.py")
    candidate = subject.git_entry(head, "src/after.py")
    assert before is not None and candidate is not None

    with subject.disposable_checkout(
        repository,
        head,
        reverse_rename=("src/before.py", "src/after.py", before, candidate),
    ) as checkout:
        state = checkout.parent
        assert not state.resolve().is_relative_to(repository.resolve())
        assert os.stat(state).st_dev == os.stat(repository).st_dev
        assert not old.exists()
        assert new.read_bytes() == b"VALUE = 'guarded'\n"
        assert (checkout / "src" / "before.py").read_bytes() == b"VALUE = 'guarded'\n"
        assert not (checkout / "src" / "after.py").exists()

    assert not state.exists()
    assert not old.exists()
    assert new.read_bytes() == b"VALUE = 'guarded'\n"


def test_interrupted_partial_mutant_write_cannot_touch_the_source_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, old, new = _candidate_rename(repository)
    head = _git(repository, "rev-parse", "HEAD")
    monkeypatch.chdir(repository)
    before = subject.git_entry(base, "src/before.py")
    candidate = subject.git_entry(head, "src/after.py")
    assert before is not None and candidate is not None
    attempted_paths: list[Path] = []

    def interrupt_atomic_rename(source: Path, destination: Path) -> None:
        attempted_paths.extend((Path(source), Path(destination)))
        raise RuntimeError("simulated interruption at atomic disposable rename")

    monkeypatch.setattr(subject.os, "replace", interrupt_atomic_rename)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        with subject.disposable_checkout(
            repository,
            head,
            reverse_rename=("src/before.py", "src/after.py", before, candidate),
        ):
            raise AssertionError("interrupted mutation yielded a checkout")

    assert attempted_paths
    assert all(not path.resolve(strict=False).is_relative_to(repository.resolve()) for path in attempted_paths)
    assert not old.exists()
    assert new.read_bytes() == b"VALUE = 'guarded'\n"


def test_disposable_state_is_not_visible_inside_the_measured_checkout(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    base, old, new = _candidate_rename(repository)
    runs = 0

    def detect_state(_suites: list[str], _cache: Path, **kwargs) -> list[str]:
        nonlocal runs
        runs += 1
        checkout = Path(kwargs["root"])
        visible = (checkout / subject._STATE_DIRECTORY_NAME).exists() or (
            repository / subject._STATE_DIRECTORY_NAME
        ).exists()
        return ["test_checkout_has_no_measurement_state"] if visible else []

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", detect_state)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 1
    assert runs == 3
    assert not old.exists()
    assert new.read_bytes() == b"VALUE = 'guarded'\n"
    assert not (repository / subject._STATE_DIRECTORY_NAME).exists()


@pytest.mark.parametrize(
    "unsafe",
    [r"..\outside\sentinel.py", "../outside/sentinel.py", "C:/outside/sentinel.py", r"\\host\share\file.py"],
)
def test_repository_path_validation_rejects_windows_and_posix_escapes(tmp_path: Path, unsafe: str) -> None:
    outside = tmp_path / "outside" / "sentinel.py"
    outside.parent.mkdir()
    outside.write_bytes(b"EXTERNAL\n")

    with pytest.raises(subject.MeasurementError, match="unsafe repository path"):
        subject._safe_relative(unsafe)

    assert outside.read_bytes() == b"EXTERNAL\n"


def test_unsettled_mutant_preserves_only_external_disposable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, old, new = _candidate_rename(repository)
    calls = 0

    def lose_settlement(_suites: list[str], _cache: Path, **_kwargs) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        raise subject.UnsettledProcessTree("simulated unverified descendant")

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", lose_settlement)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 2
    output = capsys.readouterr().out
    state_root = subject._state_directory(repository)
    preserved = list(state_root.glob("measurement-*"))
    assert calls == 2
    assert preserved and all((path / "checkout").exists() for path in preserved)
    assert "mutant process tree did not settle" in output
    assert "disposable checkout preserved at" in output
    assert not old.exists()
    assert new.read_bytes() == b"VALUE = 'guarded'\n"

    for path in preserved:
        resolved = path.resolve(strict=True)
        assert resolved.parent == state_root.resolve(strict=True)
        subject._remove_disposable_state(resolved, repository)
    for cache in tmp_path.glob("unguarded-run-*"):
        resolved = cache.resolve(strict=True)
        assert resolved.parent == tmp_path.resolve(strict=True)
        shutil.rmtree(resolved)


@pytest.mark.skipif(os.name == "nt", reason="Windows checkouts may materialize Git symlinks as regular files")
def test_disposable_exact_rename_preserves_a_real_symlink_identity(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    target = repository / "src" / "target.py"
    old = repository / "src" / "before.py"
    new = repository / "src" / "after.py"
    target.parent.mkdir()
    target.write_text("VALUE = True\n", encoding="utf-8")
    os.symlink("target.py", old)
    _git(repository, "add", "src/target.py", "src/before.py")
    _git(repository, "commit", "-qm", "base symlink")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "src/before.py", "src/after.py")
    _git(repository, "commit", "-qm", "rename symlink")
    head = _git(repository, "rev-parse", "HEAD")
    monkeypatch.chdir(repository)
    before = subject.git_entry(base, "src/before.py")
    candidate = subject.git_entry(head, "src/after.py")
    assert before is not None and candidate is not None and before.mode == "120000"

    with subject.disposable_checkout(
        repository,
        head,
        reverse_rename=("src/before.py", "src/after.py", before, candidate),
    ) as checkout:
        link = checkout / "src" / "before.py"
        assert link.is_symlink()
        assert os.readlink(link) == "target.py"
        assert not (checkout / "src" / "after.py").exists()

    assert not old.exists()
    assert new.is_symlink()
    assert os.readlink(new) == "target.py"


def _commit_real_rename_guard(repository: Path) -> Path:
    tests = repository / "tests"
    tests.mkdir(exist_ok=True)
    guard = tests / "test_guard.py"
    guard.write_text(
        "from pathlib import Path\n\n"
        "def test_candidate_name_exists():\n"
        "    root = Path(__file__).resolve().parents[1]\n"
        "    assert not (root / 'src' / 'before.py').exists()\n"
        "    assert (root / 'src' / 'after.py').is_file()\n",
        encoding="utf-8",
    )
    (tests / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    _git(repository, "add", "tests/test_guard.py", "tests/test_smoke.py")
    _git(repository, "commit", "-qm", "guard candidate rename")
    return guard


def _commit_measurement_only_suite(repository: Path, name: str, body: str) -> str:
    relative = f"tests/{name}.py"
    path = repository / relative
    path.parent.mkdir(exist_ok=True)
    path.write_text(body, encoding="utf-8")
    _git(repository, "add", relative)
    _git(repository, "commit", "-qm", f"add {name}")
    return relative


def test_main_refuses_a_clean_head_advance_after_candidate_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    guard = _commit_real_rename_guard(repository)
    original_roster = subject.default_runtime_includes
    advanced = False

    def advance_head_after_snapshot(*points: str) -> tuple[str, ...]:
        nonlocal advanced
        if not advanced:
            advanced = True
            guard.unlink()
            _git(repository, "add", "-u")
            _git(repository, "commit", "-qm", "remove the only rename guard")
        return original_roster(*points)

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "default_runtime_includes", advance_head_after_snapshot)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 2
    output = capsys.readouterr().out
    assert "source inputs drifted during candidate discovery" in output
    assert "HEAD moved" in output
    assert not guard.exists()
    assert _git(repository, "status", "--porcelain=v1") == ""


def test_main_refuses_a_stable_dirty_guard_deleted_after_the_old_porcelain_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    guard = _commit_real_rename_guard(repository)
    original_capture = subject.capture_suite_inputs
    deleted = False

    def delete_guard_before_snapshot(root: Path) -> subject.SuiteInputs:
        nonlocal deleted
        if root.resolve() == repository.resolve() and not deleted:
            deleted = True
            guard.unlink()
        return original_capture(root)

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "capture_suite_inputs", delete_guard_before_snapshot)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 2
    output = capsys.readouterr().out
    assert "uncommitted candidate inputs cannot be attributed to HEAD" in output
    assert not guard.exists()
    assert "tests/test_guard.py" in _git(repository, "status", "--porcelain=v1")


def test_main_does_not_expose_mutant_phase_through_the_pycache_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    suite = _commit_measurement_only_suite(
        repository,
        "test_phase_neutral",
        "import os\n\ndef test_not_labelled_mutant():\n    assert 'mutant' not in os.environ['PYTHONPYCACHEPREFIX']\n",
    )
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        sys,
        "argv",
        ["unguarded_production_files", "--base", base, "--suite", suite],
    )

    assert subject.main() == 1
    output = capsys.readouterr().out
    assert "0 new - UNGUARDED" in output
    assert "every isolated production artifact introduced a new failure" not in output


def test_main_keeps_control_and_mutant_git_status_equally_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    suite = _commit_measurement_only_suite(
        repository,
        "test_clean_checkout",
        "import subprocess\n\n"
        "def test_checkout_is_clean():\n"
        "    run = subprocess.run(['git', 'status', '--porcelain'], check=True, capture_output=True, text=True)\n"
        "    assert run.stdout == ''\n",
    )
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        sys,
        "argv",
        ["unguarded_production_files", "--base", base, "--suite", suite],
    )

    assert subject.main() == 1
    output = capsys.readouterr().out
    assert "0 new - UNGUARDED" in output
    assert "every isolated production artifact introduced a new failure" not in output


def test_main_strips_source_and_protected_authority_from_real_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    suite = _commit_measurement_only_suite(
        repository,
        "test_candidate_authority",
        "import os\n"
        "import subprocess\n"
        "from pathlib import Path\n\n"
        "def test_candidate_has_no_source_authority():\n"
        "    for key in ('GITHUB_TOKEN', 'GITHUB_WORKSPACE', 'GIT_DIR', 'OLDPWD'):\n"
        "        assert key not in os.environ\n"
        "    assert Path(os.environ['PWD']).resolve() == Path.cwd().resolve()\n"
        "    remote = subprocess.run(['git', 'remote'], check=True, capture_output=True, text=True)\n"
        "    assert remote.stdout == ''\n",
    )
    monkeypatch.setenv("GITHUB_TOKEN", "protected")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repository))
    monkeypatch.setenv("GIT_DIR", str(repository / ".git"))
    monkeypatch.setenv("PWD", str(repository))
    monkeypatch.setenv("OLDPWD", str(repository))
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        sys,
        "argv",
        ["unguarded_production_files", "--base", base, "--suite", suite],
    )

    assert subject.main() == 1
    output = capsys.readouterr().out
    assert "0 new - UNGUARDED" in output
    assert "every isolated production artifact introduced a new failure" not in output


@pytest.mark.parametrize(
    "selector",
    (
        "../tests",
        "-p",
        "src/cryodaq",
        "tests/../src",
        "tests\\test_escape.py",
        "C:/outside/test_escape.py",
    ),
)
def test_failures_rejects_unconfined_or_option_like_suite_selectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selector: str
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "tests").mkdir(parents=True)
    run_root = tmp_path / "run"
    run_root.mkdir()

    def must_not_launch(*_args, **_kwargs):
        raise AssertionError("unconfined selector reached the pytest process")

    monkeypatch.setattr(subject, "_run_candidate_process", must_not_launch)

    with pytest.raises(subject.MeasurementError, match="pytest suite selector|unsafe repository path"):
        subject.failures([selector], run_root, root=checkout, source_root=checkout)


def test_changed_files_selects_runtime_assets_without_a_suffix_allowlist(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    marker = repository / "README"
    marker.write_text("base\n", encoding="utf-8")
    _git(repository, "add", "README")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")
    runtime_asset = repository / "src" / "cryodaq" / "web" / "static" / "operator-display.html"
    runtime_asset.parent.mkdir(parents=True)
    runtime_asset.write_text("<output>measurement</output>\n", encoding="utf-8")
    _git(repository, "add", runtime_asset.relative_to(repository).as_posix())
    _git(repository, "commit", "-qm", "add runtime display asset")
    head = _git(repository, "rev-parse", "HEAD")
    monkeypatch.chdir(repository)

    includes = subject.default_runtime_includes(base, head)
    selected = {path for artifact in subject.changed_files(base, head, includes) for path in artifact.paths}

    assert runtime_asset.relative_to(repository).as_posix() in selected


def test_disposable_checkout_rejects_clean_filter_transformed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    (repository / ".gitattributes").write_text("payload.txt text eol=crlf\n", encoding="utf-8")
    (repository / "payload.txt").write_bytes(b"candidate\n")
    _git(repository, "add", ".gitattributes", "payload.txt")
    _git(repository, "commit", "-qm", "add checkout transform")
    head = _git(repository, "rev-parse", "HEAD")
    monkeypatch.chdir(repository)

    with pytest.raises(subject.MeasurementError, match="raw blob identity"):
        with subject.disposable_checkout(repository, head):
            raise AssertionError("transformed checkout was accepted")


@pytest.mark.skipif(os.name == "nt", reason="creating directory symlinks is not portable on Windows")
def test_checkout_path_rejects_a_real_symlink_parent(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    outside = tmp_path / "outside"
    checkout.mkdir()
    outside.mkdir()
    os.symlink(outside, checkout / "linked", target_is_directory=True)

    with pytest.raises(subject.MeasurementError, match="parent is a link or junction"):
        subject._checkout_path(checkout, "linked/production.py")


def test_concurrent_source_target_writer_is_preserved_and_refuses_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, candidate = _candidate_rename(repository)
    calls = 0

    def write_source_during_mutant(_suites: list[str], _run_root: Path, **_kwargs) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            candidate.write_bytes(b"VALUE = 'concurrent writer'\n")
        return [] if calls == 1 else ["test_candidate_name_exists"]

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject, "failures", write_source_during_mutant)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 2
    assert candidate.read_bytes() == b"VALUE = 'concurrent writer'\n"
    assert "suite inputs drifted during mutation attribution" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ("--skip-worktree", "--assume-unchanged"))
def test_main_rejects_a_hidden_index_guard_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: str,
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    guard = _commit_real_rename_guard(repository)
    _git(repository, "update-index", flag, "tests/test_guard.py")
    guard.unlink()
    assert _git(repository, "status", "--porcelain=v1") == ""

    monkeypatch.chdir(repository)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", "tests"])

    assert subject.main() == 2
    output = capsys.readouterr().out
    assert "nonordinary Git index flags can hide candidate inputs" in output
    assert "tests/test_guard.py" in output
    assert not guard.exists()


def test_main_rebinds_inherited_candidate_sha_to_each_synthetic_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    source_head = _git(repository, "rev-parse", "HEAD")
    suite = _commit_measurement_only_suite(
        repository,
        "test_candidate_sha",
        "import os\n"
        "import subprocess\n\n"
        "def test_head_tree_matches_bound_candidate():\n"
        "    bound = subprocess.run(['git', 'diff', '--quiet', os.environ['GITHUB_SHA'], 'HEAD'])\n"
        "    ancestry = subprocess.run(['git', 'diff', '--quiet', 'HEAD^', 'HEAD'])\n"
        "    assert bound.returncode == ancestry.returncode == 0\n",
    )
    monkeypatch.setenv("GITHUB_SHA", source_head)
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        sys,
        "argv",
        ["unguarded_production_files", "--base", base, "--suite", suite],
    )

    assert subject.main() == 1
    output = capsys.readouterr().out
    assert "0 new - UNGUARDED" in output
    assert "every isolated production artifact introduced a new failure" not in output


def test_disposable_candidate_and_mutant_have_only_phase_neutral_git_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    source_head = _git(repository, "rev-parse", "HEAD")
    monkeypatch.chdir(repository)
    before = subject.git_entry(base, "src/before.py")
    candidate = subject.git_entry(source_head, "src/after.py")
    assert before is not None and candidate is not None

    for reverse_rename in (
        None,
        ("src/before.py", "src/after.py", before, candidate),
    ):
        with subject.disposable_checkout(
            repository,
            source_head,
            reverse_rename=reverse_rename,
        ) as checkout:
            assert _git(checkout, "rev-list", "--count", "HEAD") == "2"
            assert _git(checkout, "diff", "--quiet", "HEAD^", "HEAD") == ""
            assert _git(checkout, "for-each-ref", "--format=%(refname)") == ""
            assert _git(checkout, "remote") == ""
            assert (
                subprocess.run(
                    ["git", "-C", str(checkout), "rev-parse", "--verify", "HEAD@{1}"],
                    capture_output=True,
                ).returncode
                != 0
            )
            assert (
                subprocess.run(
                    ["git", "-C", str(checkout), "cat-file", "-e", f"{source_head}^{{commit}}"],
                    capture_output=True,
                ).returncode
                != 0
            )
            unreachable = subprocess.run(
                ["git", "-C", str(checkout), "fsck", "--unreachable", "--no-reflogs"],
                check=True,
                capture_output=True,
                text=True,
            )
            assert unreachable.stdout == ""


def test_main_real_pytest_attributes_an_exact_rename_to_its_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    _commit_real_rename_guard(repository)
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "unguarded_production_files",
            "--base",
            base,
            "--suite",
            "tests/test_guard.py",
        ],
    )

    assert subject.main() == 0
    output = capsys.readouterr().out
    assert "test_candidate_name_exists" in output
    assert "every isolated production artifact introduced a new failure" in output


def test_main_does_not_certify_a_mutant_only_empty_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / "src" / "old_parent" / "artifact.py"
    old.parent.mkdir(parents=True)
    old.write_text("VALUE = 'before'\n", encoding="utf-8")
    _git(repository, "add", "src/old_parent/artifact.py")
    _git(repository, "commit", "-qm", "base")
    base = _git(repository, "rev-parse", "HEAD")

    new = repository / "src" / "new_parent" / "artifact.py"
    new.parent.mkdir(parents=True)
    old.replace(new)
    old.parent.rmdir()
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "rename production artifact")
    suite = _commit_measurement_only_suite(
        repository,
        "test_no_empty_directories",
        "from pathlib import Path\n\n"
        "def test_no_empty_directories():\n"
        "    empty = [str(path) for path in Path('src').rglob('*') "
        "if path.is_dir() and not any(path.iterdir())]\n"
        "    assert not empty, empty\n",
    )
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        sys,
        "argv",
        ["unguarded_production_files", "--base", base, "--suite", suite],
    )

    assert subject.main() == 1
    output = capsys.readouterr().out
    assert "0 new - UNGUARDED" in output
    assert "every isolated production artifact introduced a new failure" not in output


def test_main_does_not_expose_a_mutant_only_checkout_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    suite = _commit_measurement_only_suite(
        repository,
        "test_checkout_path_identity",
        "from pathlib import Path\n\n"
        "def test_checkout_path_is_phase_neutral():\n"
        "    assert Path.cwd().parent.name != 'measurement-mutant'\n",
    )
    original_mkdtemp = subject.tempfile.mkdtemp
    phase_names = iter(("measurement-control", "measurement-mutant", "measurement-confirmation"))
    run_index = 0

    def allocated_mkdtemp(*, prefix: str = "tmp", suffix: str = "", dir: str | Path | None = None) -> str:
        nonlocal run_index
        if prefix == "measurement-":
            path = Path(dir) / next(phase_names)
        elif prefix == "unguarded-run-":
            run_index += 1
            path = tmp_path / f"unguarded-run-{run_index}"
        else:
            return original_mkdtemp(prefix=prefix, suffix=suffix, dir=dir)
        path.mkdir()
        return str(path)

    monkeypatch.setattr(subject.tempfile, "mkdtemp", allocated_mkdtemp)
    monkeypatch.chdir(repository)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", suite])

    assert subject.main() == 1
    output = capsys.readouterr().out
    assert "0 new - UNGUARDED" in output
    assert "every isolated production artifact introduced a new failure" not in output


def test_main_does_not_inherit_arbitrary_candidate_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    suite = _commit_measurement_only_suite(
        repository,
        "test_inherited_candidate_identity",
        "import os\n"
        "import subprocess\n\n"
        "def test_inherited_tree_is_not_a_phase_oracle():\n"
        "    tree = os.environ.get('ARBITRARY_CANDIDATE_TREE_SENTINEL')\n"
        "    if tree is not None:\n"
        "        observed = subprocess.run(['git', 'cat-file', '-e', f'{tree}^{{tree}}'])\n"
        "        assert observed.returncode == 0\n",
    )
    candidate_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    monkeypatch.setenv("ARBITRARY_CANDIDATE_TREE_SENTINEL", candidate_tree)
    monkeypatch.chdir(repository)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", suite])

    assert subject.main() == 1
    output = capsys.readouterr().out
    assert "0 new - UNGUARDED" in output
    assert "every isolated production artifact introduced a new failure" not in output


def test_main_rebinds_product_root_away_from_the_measured_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    package = repository / "src" / "cryodaq"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"")
    source_paths = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "paths.py"
    (package / "paths.py").write_bytes(source_paths.read_bytes())
    old = repository / "plugins" / "before.py"
    old.parent.mkdir()
    old.write_bytes(b"VALUE = True\n")
    (repository / ".gitignore").write_text("config/.first_run_done\n", encoding="utf-8")
    _git(repository, "add", ".gitignore", "src/cryodaq/__init__.py", "src/cryodaq/paths.py", "plugins/before.py")
    _git(repository, "commit", "-qm", "base with production paths")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "mv", "plugins/before.py", "plugins/after.py")
    _git(repository, "commit", "-qm", "rename plugin")
    suite = _commit_measurement_only_suite(
        repository,
        "test_product_root_authority",
        "from cryodaq.paths import get_config_dir\n\n"
        "def test_product_root_write_is_disposable():\n"
        "    marker = get_config_dir() / '.first_run_done'\n"
        "    marker.parent.mkdir(parents=True, exist_ok=True)\n"
        "    marker.write_text('measurement process write', encoding='utf-8')\n",
    )
    source_marker = repository / "config" / ".first_run_done"
    monkeypatch.setenv("CRYODAQ_ROOT", str(repository))
    monkeypatch.chdir(repository)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", suite])

    result = subject.main()
    source_was_written = source_marker.exists()
    if source_was_written:
        source_marker.unlink()
        source_marker.parent.rmdir()

    assert result == 1
    assert not source_was_written
    output = capsys.readouterr().out
    assert "0 new - UNGUARDED" in output


def test_main_requires_the_same_complete_failure_node_to_repeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _repository(tmp_path / "candidate")
    base, _old, _new = _candidate_rename(repository)
    counter = tmp_path / "alternating-node-count"
    suite = _commit_measurement_only_suite(
        repository,
        "test_alternating_failure_nodes",
        "from pathlib import Path\n"
        "import pytest\n\n"
        f"COUNTER = Path({str(counter)!r})\n"
        "MUTANT = Path('src/before.py').is_file()\n"
        "if MUTANT:\n"
        "    ACTIVE = int(COUNTER.read_text(encoding='ascii')) if COUNTER.exists() else 0\n"
        "    COUNTER.write_text(str(ACTIVE + 1), encoding='ascii')\n"
        "else:\n"
        "    ACTIVE = -1\n\n"
        "class TestA:\n"
        "    def test_guard(self):\n"
        "        if ACTIVE == 0:\n"
        "            pytest.fail('coverage signal')\n\n"
        "class TestB:\n"
        "    def test_guard(self):\n"
        "        if ACTIVE == 1:\n"
        "            pytest.fail('coverage signal')\n",
    )
    monkeypatch.chdir(repository)
    monkeypatch.setattr(sys, "argv", ["unguarded_production_files", "--base", base, "--suite", suite])

    try:
        result = subject.main()
    finally:
        counter.unlink(missing_ok=True)

    assert result == 1
    output = capsys.readouterr().out
    assert "mutant failures did not repeat exactly" in output
    assert "every isolated production artifact introduced a new failure" not in output


def test_disposable_reverse_rename_prunes_only_the_vacated_parent_chain(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / "src" / "legacy" / "deep" / "artifact.py"
    sibling = repository / "src" / "new_parent" / "sibling.py"
    old.parent.mkdir(parents=True)
    sibling.parent.mkdir(parents=True)
    old.write_bytes(b"VALUE = True\n")
    sibling.write_bytes(b"SIBLING = True\n")
    _git(repository, "add", "src/legacy/deep/artifact.py", "src/new_parent/sibling.py")
    _git(repository, "commit", "-qm", "base nested artifact")
    base = _git(repository, "rev-parse", "HEAD")
    new = repository / "src" / "new_parent" / "deep" / "deeper" / "artifact.py"
    new.parent.mkdir(parents=True)
    old.replace(new)
    old.parent.rmdir()
    old.parent.parent.rmdir()
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "rename nested artifact")
    head = _git(repository, "rev-parse", "HEAD")
    before = subject.git_entry_at(repository, base, "src/legacy/deep/artifact.py")
    candidate = subject.git_entry_at(repository, head, "src/new_parent/deep/deeper/artifact.py")
    assert before is not None and candidate is not None
    monkeypatch.chdir(repository)

    with subject.disposable_checkout(
        repository,
        head,
        reverse_rename=(
            "src/legacy/deep/artifact.py",
            "src/new_parent/deep/deeper/artifact.py",
            before,
            candidate,
        ),
    ) as checkout:
        assert (checkout / "src" / "legacy" / "deep" / "artifact.py").read_bytes() == b"VALUE = True\n"
        assert not (checkout / "src" / "new_parent" / "deep").exists()
        assert (checkout / "src" / "new_parent" / "sibling.py").read_bytes() == b"SIBLING = True\n"


@pytest.mark.parametrize(
    ("old_relative", "new_relative"),
    (
        ("src/node", "src/node/deep/artifact.py"),
        ("src/node/deep/artifact.py", "src/node"),
    ),
)
def test_disposable_reverse_rename_handles_file_directory_prefixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old_relative: str,
    new_relative: str,
) -> None:
    repository = _repository(tmp_path / "candidate")
    _git(repository, "config", "core.autocrlf", "false")
    old = repository / old_relative
    old.parent.mkdir(parents=True)
    old.write_bytes(b"VALUE = 'same entry'\n")
    _git(repository, "add", old_relative)
    _git(repository, "commit", "-qm", "base prefix entry")
    base = _git(repository, "rev-parse", "HEAD")
    payload = old.read_bytes()
    old.unlink()
    current = old.parent
    source_root = repository / "src"
    while current != source_root and not any(current.iterdir()):
        parent = current.parent
        current.rmdir()
        current = parent
    new = repository / new_relative
    new.parent.mkdir(parents=True, exist_ok=True)
    new.write_bytes(payload)
    _git(repository, "add", "-A")
    _git(repository, "commit", "-qm", "rename across file directory prefix")
    head = _git(repository, "rev-parse", "HEAD")
    before = subject.git_entry_at(repository, base, old_relative)
    candidate = subject.git_entry_at(repository, head, new_relative)
    assert before is not None and candidate is not None
    monkeypatch.chdir(repository)

    with subject.disposable_checkout(
        repository,
        head,
        reverse_rename=(old_relative, new_relative, before, candidate),
    ) as checkout:
        assert (checkout / old_relative).read_bytes() == payload
        candidate_path = checkout / new_relative
        if PurePosixPath(old_relative).is_relative_to(PurePosixPath(new_relative)):
            assert candidate_path.is_dir()
        else:
            assert not candidate_path.exists()
        assert not subject.path_matches_git_entry(candidate_path, candidate)


@pytest.mark.skipif(os.name == "nt", reason="Windows checkouts may not materialize Git symlinks")
def test_disposable_checkout_rejects_a_tracked_symlink_resolving_outside_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path / "candidate")
    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 'outside'\n", encoding="utf-8")
    link = repository / "src" / "outside.py"
    link.parent.mkdir()
    os.symlink(outside, link)
    _git(repository, "add", "src/outside.py")
    _git(repository, "commit", "-qm", "tracked external symlink")
    head = _git(repository, "rev-parse", "HEAD")
    monkeypatch.chdir(repository)

    with pytest.raises(subject.MeasurementError, match="resolves outside the disposable checkout"):
        with subject.disposable_checkout(repository, head):
            raise AssertionError("external tracked symlink reached candidate execution")
