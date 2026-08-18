from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from cryodaq.core import qualification
from cryodaq.core.qualification import QualificationReceiptError, source_checkout_qualification_context
from tests.qualification_support import issued_simulation_binding


def _fake_git_identity(command: list[str], **_kwargs: object) -> SimpleNamespace:
    value = "a" if command[-1] == "HEAD" else "b"
    return SimpleNamespace(stdout=value * 40 + "\n")


def test_source_checkout_identity_changes_when_runtime_plugin_changes(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    package_root = project_root / "src" / "cryodaq"
    config_root = project_root / "config"
    plugins_root = project_root / "plugins"
    package_root.mkdir(parents=True)
    config_root.mkdir()
    plugins_root.mkdir()
    (package_root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (config_root / "instruments.yaml").write_text("instruments: []\n", encoding="utf-8")
    plugin_path = plugins_root / "runtime_plugin.py"
    plugin_path.write_text("VALUE = 1\n", encoding="utf-8")
    (plugins_root / "runtime_plugin.yaml").write_text("enabled: true\n", encoding="utf-8")

    monkeypatch.setattr(qualification.subprocess, "run", _fake_git_identity)
    reviewed_source = object()
    runtime_binding = issued_simulation_binding(reviewed_source, "test-registry")

    before = source_checkout_qualification_context(
        project_root=project_root,
        config_directory=config_root,
        reviewed_source=reviewed_source,
        runtime_binding=runtime_binding,
    )
    plugin_path.write_text("VALUE = 2\n", encoding="utf-8")
    after = source_checkout_qualification_context(
        project_root=project_root,
        config_directory=config_root,
        reviewed_source=reviewed_source,
        runtime_binding=runtime_binding,
    )

    assert after.artifact_sha256 != before.artifact_sha256
    assert after.configuration_sha256 == before.configuration_sha256


def test_qualification_captures_plugin_snapshot_from_the_measured_bytes(tmp_path: Path, monkeypatch) -> None:
    """The plugin snapshot is the exact bytes the context's artifact digest certifies."""

    project_root = tmp_path / "project"
    package_root = project_root / "src" / "cryodaq"
    config_root = project_root / "config"
    plugins_root = project_root / "plugins"
    package_root.mkdir(parents=True)
    config_root.mkdir()
    plugins_root.mkdir()
    (package_root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (config_root / "instruments.yaml").write_text("instruments: []\n", encoding="utf-8")
    plugin_path = plugins_root / "runtime_plugin.py"
    plugin_path.write_bytes(b"VALUE = 1\n")
    plugin_yaml = plugins_root / "runtime_plugin.yaml"
    plugin_yaml.write_bytes(b"enabled: true\n")

    monkeypatch.setattr(qualification.subprocess, "run", _fake_git_identity)
    reviewed_source = object()
    runtime_binding = issued_simulation_binding(reviewed_source, "test-registry")

    snapshot: dict[str, str] = {}
    context = source_checkout_qualification_context(
        project_root=project_root,
        config_directory=config_root,
        reviewed_source=reviewed_source,
        runtime_binding=runtime_binding,
        plugins_snapshot=snapshot,
    )

    expected = {
        "runtime_plugin.py": hashlib.sha256(b"VALUE = 1\n").hexdigest(),
        "runtime_plugin.yaml": hashlib.sha256(b"enabled: true\n").hexdigest(),
    }
    assert snapshot == expected

    plugin_path.write_bytes(b"VALUE = 2\n")
    changed_snapshot: dict[str, str] = {}
    changed = source_checkout_qualification_context(
        project_root=project_root,
        config_directory=config_root,
        reviewed_source=reviewed_source,
        runtime_binding=runtime_binding,
        plugins_snapshot=changed_snapshot,
    )

    assert changed_snapshot["runtime_plugin.py"] == hashlib.sha256(b"VALUE = 2\n").hexdigest()
    assert changed_snapshot["runtime_plugin.yaml"] == expected["runtime_plugin.yaml"]
    assert changed.artifact_sha256 != context.artifact_sha256


def test_qualification_plugin_snapshot_is_empty_without_plugins_root(tmp_path: Path, monkeypatch) -> None:
    """No plugin root means no frozen plugin bytes to bind."""

    project_root = tmp_path / "project"
    package_root = project_root / "src" / "cryodaq"
    config_root = project_root / "config"
    package_root.mkdir(parents=True)
    config_root.mkdir()
    (package_root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (config_root / "instruments.yaml").write_text("instruments: []\n", encoding="utf-8")

    monkeypatch.setattr(qualification.subprocess, "run", _fake_git_identity)
    reviewed_source = object()
    runtime_binding = issued_simulation_binding(reviewed_source, "test-registry")

    snapshot: dict[str, str] = {}
    source_checkout_qualification_context(
        project_root=project_root,
        config_directory=config_root,
        reviewed_source=reviewed_source,
        runtime_binding=runtime_binding,
        plugins_snapshot=snapshot,
    )

    assert snapshot == {}


def test_source_checkout_identity_refuses_when_source_package_is_missing(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    plugins_root = project_root / "plugins"
    config_root.mkdir(parents=True)
    plugins_root.mkdir()
    (config_root / "instruments.yaml").write_text("instruments: []\n", encoding="utf-8")
    (plugins_root / "runtime_plugin.py").write_text("VALUE = 1\n", encoding="utf-8")

    def fake_git(command: list[str], **_kwargs: object) -> SimpleNamespace:
        value = "a" if command[-1] == "HEAD" else "b"
        return SimpleNamespace(stdout=value * 40 + "\n")

    monkeypatch.setattr(qualification.subprocess, "run", fake_git)
    reviewed_source = object()
    runtime_binding = issued_simulation_binding(reviewed_source, "test-registry")

    with pytest.raises(QualificationReceiptError, match="source package manifest is unavailable"):
        source_checkout_qualification_context(
            project_root=project_root,
            config_directory=config_root,
            reviewed_source=reviewed_source,
            runtime_binding=runtime_binding,
        )


def test_source_checkout_identity_refuses_when_source_package_is_empty(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    package_root = project_root / "src" / "cryodaq"
    config_root = project_root / "config"
    plugins_root = project_root / "plugins"
    package_root.mkdir(parents=True)
    config_root.mkdir()
    plugins_root.mkdir()
    (config_root / "instruments.yaml").write_text("instruments: []" + chr(10), encoding="utf-8")
    (plugins_root / "runtime_plugin.py").write_text("VALUE = 1" + chr(10), encoding="utf-8")

    def fake_git(command: list[str], **_kwargs: object) -> SimpleNamespace:
        value = "a" if command[-1] == "HEAD" else "b"
        return SimpleNamespace(stdout=value * 40 + chr(10))

    monkeypatch.setattr(qualification.subprocess, "run", fake_git)
    reviewed_source = object()
    runtime_binding = issued_simulation_binding(reviewed_source, "test-registry")

    with pytest.raises(QualificationReceiptError, match="source package manifest is empty"):
        source_checkout_qualification_context(
            project_root=project_root,
            config_directory=config_root,
            reviewed_source=reviewed_source,
            runtime_binding=runtime_binding,
        )
