from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cryodaq.core import qualification
from cryodaq.core.qualification import source_checkout_qualification_context
from tests.qualification_support import issued_simulation_binding


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

    def fake_git(command: list[str], **_kwargs: object) -> SimpleNamespace:
        value = "a" if command[-1] == "HEAD" else "b"
        return SimpleNamespace(stdout=value * 40 + "\n")

    monkeypatch.setattr(qualification.subprocess, "run", fake_git)
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
