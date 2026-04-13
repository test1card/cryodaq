"""Test ``paths.py`` behaviour in frozen and dev modes."""
from __future__ import annotations

import sys

from cryodaq import paths


def test_dev_mode_returns_repo_root(monkeypatch):
    """In editable install, root should be the repo containing src/cryodaq."""
    monkeypatch.delenv("CRYODAQ_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    if hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    root = paths.get_project_root()
    assert (root / "src" / "cryodaq").exists(), f"Expected repo root, got {root}"


def test_cryodaq_root_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    assert paths.get_project_root() == tmp_path.resolve()


def test_is_frozen_false_in_dev(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    if hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert paths.is_frozen() is False


def test_frozen_mode_uses_sys_executable_parent(tmp_path, monkeypatch):
    """When ``sys.frozen`` is set, root must be ``sys.executable.parent``,
    NOT ``_MEIPASS`` (which is wiped on exit)."""
    fake_exe = tmp_path / "CryoDAQ"
    fake_exe.write_text("", encoding="utf-8")
    meipass = tmp_path / "_MEIPASS_temp"
    meipass.mkdir()

    monkeypatch.delenv("CRYODAQ_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)

    root = paths.get_project_root()
    assert root == tmp_path.resolve(), (
        f"Frozen root must be next to exe ({tmp_path}), "
        f"NOT _MEIPASS ({meipass}). Got: {root}"
    )
    assert paths.is_frozen() is True


def test_frozen_tsp_dir_is_inside_meipass(tmp_path, monkeypatch):
    """TSP scripts ARE bundled (read-only constants) → inside ``_MEIPASS``."""
    fake_exe = tmp_path / "CryoDAQ"
    fake_exe.write_text("", encoding="utf-8")
    meipass = tmp_path / "_MEIPASS_temp"
    meipass.mkdir()

    monkeypatch.delenv("CRYODAQ_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)

    tsp = paths.get_tsp_dir()
    assert str(tsp).startswith(str(meipass)), (
        f"TSP dir should be inside _MEIPASS (read-only bundle), got {tsp}"
    )


def test_cryodaq_root_overrides_frozen(tmp_path, monkeypatch):
    """Explicit ``CRYODAQ_ROOT`` wins even in frozen mode."""
    override = tmp_path / "override"
    override.mkdir()
    fake_exe = tmp_path / "CryoDAQ"
    fake_exe.write_text("", encoding="utf-8")

    monkeypatch.setenv("CRYODAQ_ROOT", str(override))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)

    assert paths.get_project_root() == override.resolve()


def test_get_data_dir_creates_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    d = paths.get_data_dir()
    assert d.exists() and d.is_dir()
    assert d == (tmp_path / "data").resolve()


def test_get_logs_dir_creates_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    d = paths.get_logs_dir()
    assert d.exists() and d.is_dir()
    assert d == (tmp_path / "logs").resolve()
