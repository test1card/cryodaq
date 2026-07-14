from __future__ import annotations

from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
PINNED_MINICONDA = "conda-incubator/setup-miniconda@8ee1f361103df19b6f8c8655fd3967a8ecb162d5"


def test_supported_test_workflows_use_safe_tracked_runtime() -> None:
    for relative in (
        ".github/workflows/main.yml",
        ".github/workflows/nightly.yml",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert PINNED_MINICONDA in text
        assert "environment-file: environment.yml" in text
        assert "pip install -r requirements-lock.txt" in text
        assert "pip install -e . --no-deps" in text
        assert "pip check" in text
        assert "Verify safe SQLite runtime" in text
        assert "actions/setup-python" not in text


def test_pip_lock_preserves_platform_specific_runtime_dependencies() -> None:
    lines = (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
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
