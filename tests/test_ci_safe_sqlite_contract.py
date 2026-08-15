from __future__ import annotations

from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement

from cryodaq.storage._sqlite import SQLITE_BACKPORT_SAFE, SQLITE_BROKEN_RANGE

ROOT = Path(__file__).resolve().parents[1]
PINNED_MINICONDA = "conda-incubator/setup-miniconda@8ee1f361103df19b6f8c8655fd3967a8ecb162d5"


#: The exact patch measured by the supported-platform candidate run. A future
#: patch requires its own evidence before this value can change.
APPROVED_PYTHON_PATCH = "3.14.6"


def _environment_python_spec() -> str:
    """Return the `python=...` dependency verbatim from environment.yml.

    Parsed as text rather than with a YAML loader: the guard must fail if the
    entry is missing entirely, and a loader would just return None for that.
    """
    text = (ROOT / "environment.yml").read_text(encoding="utf-8")
    specs = [
        line.strip().lstrip("-").strip()
        for line in text.splitlines()
        if line.strip().lstrip("-").strip().startswith("python=")
    ]
    assert len(specs) == 1, f"environment.yml must pin python exactly once; found {specs}"
    return specs[0]


def test_environment_pins_an_exact_python_patch() -> None:
    """A floating `python=3.14` would silently reopen resolution to a bad patch.

    `test_supported_test_workflows_use_safe_tracked_runtime` only checks that
    the workflows REFERENCE environment.yml; it never reads the interpreter
    entry, so reverting the pin would leave it green. This is the guard that
    actually binds the patch.
    """
    spec = _environment_python_spec()
    version = spec.split("=", 1)[1]

    assert version.count(".") == 2, (
        f"environment.yml pins {spec!r}: the Python patch must be exact, not left to the solver. "
        "A minor-only pin resolves to whatever conda-forge serves on the day the laboratory "
        "machine is installed."
    )
    assert version == APPROVED_PYTHON_PATCH, (
        f"environment.yml pins {spec!r}; the approved evidence-backed patch is python={APPROVED_PYTHON_PATCH}"
    )


def test_supported_test_workflows_use_safe_tracked_runtime() -> None:
    for relative in (
        ".github/workflows/main.yml",
        ".github/workflows/nightly.yml",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert PINNED_MINICONDA in text
        assert "environment-file: environment.yml" in text
        assert "python -m pip install -r requirements-lock.txt" in text
        assert "python -m pip install -e . --no-deps --no-build-isolation" in text
        assert "python -m pip check" in text
        assert "Verify safe SQLite runtime" in text
        assert "actions/setup-python" not in text


def test_main_ci_binds_h4_alias_to_the_running_linux_interpreter_fail_closed() -> None:
    text = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
    install = text.index("- name: Install dependencies")
    binding = text.index("- name: Bind H4 reviewed interpreter alias (Linux)")
    first_test = text.index("- name: Run exact exported candidate suite")

    assert install < binding < first_test
    assert "if: runner.os == 'Linux'" in text[binding:first_test]
    assert "[ -e .venv ] || [ -L .venv ]" in text[binding:first_test]
    assert 'ln -s -- "$(command -v python)" .venv/bin/python' in text[binding:first_test]
    assert "Path('/proc/self/exe').resolve(strict=True)" in text[binding:first_test]


def test_pip_lock_preserves_platform_specific_runtime_dependencies() -> None:
    lines = (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
    assert "--all-build-deps" in "\n".join(lines[:8])
    requirements = {
        requirement.name.lower(): requirement
        for line in lines
        if (text := line.strip()) and not text.startswith("#")
        for requirement in (Requirement(text),)
    }

    def selected(name: str, platform: str, implementation: str = "CPython") -> bool:
        requirement = requirements[name]
        environment = default_environment()
        environment.update(
            sys_platform=platform,
            platform_python_implementation=implementation,
        )
        return requirement.marker is None or requirement.marker.evaluate(environment)

    for name in ("colorama", "pefile", "pywin32-ctypes"):
        assert selected(name, "win32")
        assert not selected(name, "linux")
    assert not selected("uvloop", "win32")
    assert selected("uvloop", "linux")
    assert not selected("uvloop", "linux", "PyPy")
    assert selected("macholib", "darwin")
    assert not selected("macholib", "win32")
    assert not selected("macholib", "linux")


def test_windows_installer_sqlite_policy_matches_runtime_gate() -> None:
    text = (ROOT / "install.bat").read_text(encoding="ascii")
    lines = [line for line in text.splitlines() if "sqlite_version_info" in line]

    assert len(lines) == 1
    lo, hi = SQLITE_BROKEN_RANGE
    backports = tuple(sorted(SQLITE_BACKPORT_SAFE))
    expected = f"not ({lo!r} <= v < {hi!r}) or v in {backports!r}"
    condition = lines[0].split("0 if ", 1)[1].split(" else 1", 1)[0]

    assert condition.replace(" ", "") == expected.replace(" ", "")


_NIGHTLY_QT_JOB_NAMES = ("golden-replay", "mock-stack-short-soak")
_QT_LINUX_LIBRARIES = ("libegl1", "libgl1", "libxkbcommon0", "libdbus-1-3")


def _nightly_job_block(text: str, job_name: str) -> str:
    """Return one top-level nightly job, refusing ambiguous workflow structure."""

    marker = f"  {job_name}:\n"
    assert text.count(marker) == 1, f"nightly job {job_name!r} must occur exactly once"
    start = text.index(marker)
    cursor = start + len(marker)
    for line in text[cursor:].splitlines(keepends=True):
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            return text[start:cursor]
        cursor += len(line)
    return text[start:]


def _assert_nightly_qt_prerequisites(text: str) -> None:
    """Require each Qt lane to install its libraries, rather than merely name them."""

    for job_name in _NIGHTLY_QT_JOB_NAMES:
        job = _nightly_job_block(text, job_name)
        install = job.index("- name: Install Qt offscreen system libraries (Linux)")
        dependencies = job.index("- name: Install dependencies")
        assert install < dependencies, f"{job_name} installs Qt libraries after Python dependencies"
        step = job[install:dependencies]
        assert "if: runner.os == 'Linux'" in step
        assert "sudo apt-get update" in step
        install_commands = [
            line.strip().split() for line in step.splitlines() if line.strip().startswith("sudo apt-get install ")
        ]
        assert len(install_commands) == 1, f"{job_name} must contain exactly one apt-get install command"
        command = install_commands[0]
        assert command[:4] == ["sudo", "apt-get", "install", "-y"]
        for library in _QT_LINUX_LIBRARIES:
            assert library in command[4:], f"{job_name} does not install required Qt library {library!r}"


def test_nightly_qt_jobs_install_linux_prerequisites_before_dependencies() -> None:
    """Nightly Qt lanes must retain the system libraries installed in default CI."""

    text = (ROOT / ".github/workflows/nightly.yml").read_text(encoding="utf-8")
    _assert_nightly_qt_prerequisites(text)


def test_nightly_qt_guard_rejects_libraries_merely_echoed_instead_of_installed() -> None:
    """The prerequisite names alone are insufficient: apt-get must receive them."""

    text = (ROOT / ".github/workflows/nightly.yml").read_text(encoding="utf-8")
    install = "sudo apt-get install -y " + " ".join(_QT_LINUX_LIBRARIES)
    assert text.count(install) == len(_NIGHTLY_QT_JOB_NAMES)
    mutated = text.replace(install, "echo " + " ".join(_QT_LINUX_LIBRARIES))

    with pytest.raises(AssertionError, match="apt-get install command"):
        _assert_nightly_qt_prerequisites(mutated)
