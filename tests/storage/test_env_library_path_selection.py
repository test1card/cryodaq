"""The boot scripts' library correction, exercised rather than grepped.

Reviewer finding, 2026-09-06: the previous guard compared the chosen
interpreter to `command -v python3` and skipped the correction when the two were
equal — that is, whenever the environment is properly activated, which is
precisely when it is needed. Measured by the reviewer with the real script and
only the final exec replaced: env python absent from PATH -> exit 0, SQLite
3.53.2; env python present on PATH -> exit 1, CXXABI_1.3.15.

`tests/storage/test_libstdcxx_import_order.py` could not have caught that: it
asserts that certain strings appear in start.sh. These tests run the selection
with a fabricated interpreter and read back what it exported, so a rule that
looks right and behaves wrong fails here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_HELPER = Path(__file__).parents[2] / "scripts" / "cryodaq_env_library_path.sh"


def _fake_interpreter(
    directory: Path, *, prefix: Path, base_prefix: Path | None = None, name: str = "python"
) -> Path:
    """An executable that answers the two questions the helper asks.

    It ignores everything else, so no real interpreter — and no real
    environment — is needed to exercise the selection.
    """
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / name
    executable.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  *base_prefix*) echo '{base_prefix or prefix}' ;;\n"
        f"  *sys.prefix*) echo '{prefix}' ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _with_libstdcxx(prefix: Path) -> Path:
    lib = prefix / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "libstdc++.so.6").write_text("", encoding="utf-8")
    return lib


def _run_selection(interpreter: Path, *, path: str, ld_library_path: str | None = None) -> str:
    """Source the helper exactly as the boot scripts do and read back the result."""
    environment = dict(os.environ)
    environment["CRYODAQ_PY"] = str(interpreter)
    environment["PATH"] = path
    environment.pop("LD_LIBRARY_PATH", None)
    if ld_library_path is not None:
        environment["LD_LIBRARY_PATH"] = ld_library_path
    completed = subprocess.run(
        ["/bin/sh", "-c", f'. "{_HELPER}"; printf "%s" "${{LD_LIBRARY_PATH:-}}"'],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return completed.stdout


def test_the_correction_applies_when_the_environment_is_the_python3_on_path(tmp_path: Path) -> None:
    """The exact configuration the previous guard excluded.

    The old rule compared `$CRYODAQ_PY` to `command -v python3` as STRINGS, so
    reproducing it needs them to be the same string — not merely the same file.
    start.sh reaches that state through its own fallback: when the default
    interpreter path is not executable it assigns `CRYODAQ_PY="$(command -v
    python3)"`, and if that python3 is the environment's, the comparison is
    equal and the correction was skipped.
    """
    prefix = tmp_path / "env"
    lib = _with_libstdcxx(prefix)
    interpreter = _fake_interpreter(prefix / "bin", prefix=prefix, name="python3")
    path = f"{prefix / 'bin'}:/usr/bin:/bin"
    resolved = subprocess.run(
        ["/bin/sh", "-c", "command -v python3"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert resolved == str(interpreter), "precondition: the fake must BE the python3 on PATH"

    result = _run_selection(interpreter, path=path)

    assert result.split(":")[0] == str(lib), (
        "the environment's lib must be prepended even when its python IS the "
        f"python3 on PATH; got {result!r}"
    )


def test_the_correction_also_applies_when_it_is_not_on_path(tmp_path: Path) -> None:
    prefix = tmp_path / "env"
    lib = _with_libstdcxx(prefix)
    interpreter = _fake_interpreter(prefix / "bin", prefix=prefix)
    result = _run_selection(interpreter, path="/usr/bin:/bin")
    assert result.split(":")[0] == str(lib)


def test_a_prefix_without_the_library_is_not_prepended(tmp_path: Path) -> None:
    """A system interpreter reports /usr, whose libstdc++ is in a multiarch subdir.

    Prepending an arbitrary system lib directory ahead of the loader's normal
    search order is its own hazard, so the directory has to carry the library
    for the correction to mean anything.
    """
    prefix = tmp_path / "usr"
    (prefix / "lib").mkdir(parents=True)
    interpreter = _fake_interpreter(prefix / "bin", prefix=prefix)
    assert _run_selection(interpreter, path="/usr/bin:/bin") == ""


def test_a_venv_layered_on_the_environment_finds_the_base_prefix(tmp_path: Path) -> None:
    """sys.prefix is the venv and carries no libstdc++; base_prefix does."""
    base = tmp_path / "env"
    lib = _with_libstdcxx(base)
    venv = tmp_path / "venv"
    (venv / "lib").mkdir(parents=True)
    interpreter = _fake_interpreter(venv / "bin", prefix=venv, base_prefix=base)
    assert _run_selection(interpreter, path="/usr/bin:/bin").split(":")[0] == str(lib)


def test_an_existing_library_path_is_kept_behind_the_new_entry(tmp_path: Path) -> None:
    prefix = tmp_path / "env"
    lib = _with_libstdcxx(prefix)
    interpreter = _fake_interpreter(prefix / "bin", prefix=prefix)
    result = _run_selection(interpreter, path="/usr/bin:/bin", ld_library_path="/opt/vendor/lib")
    assert result == f"{lib}:/opt/vendor/lib"


def test_the_entry_is_not_duplicated_when_already_present(tmp_path: Path) -> None:
    prefix = tmp_path / "env"
    lib = _with_libstdcxx(prefix)
    interpreter = _fake_interpreter(prefix / "bin", prefix=prefix)
    result = _run_selection(interpreter, path="/usr/bin:/bin", ld_library_path=str(lib))
    assert result == str(lib)


def test_an_interpreter_that_cannot_be_run_changes_nothing(tmp_path: Path) -> None:
    """Fail open: a boot must not be blocked by a failed probe."""
    missing = tmp_path / "env" / "bin" / "python"
    assert _run_selection(missing, path="/usr/bin:/bin") == ""


@pytest.mark.parametrize("script", ["start.sh", "start_mock.sh"])
def test_both_boot_paths_source_the_helper(script: str) -> None:
    """start_mock.sh had no correction at all until 2026-09-06."""
    text = (Path(__file__).parents[2] / script).read_text(encoding="utf-8")
    assert "scripts/cryodaq_env_library_path.sh" in text, f"{script} must not drift from the other boot path"
