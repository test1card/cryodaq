from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest


class _FakeCoordinator:
    started = asyncio.Event()
    stopped = asyncio.Event()
    failed: Exception | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        self._release = asyncio.Event()

    async def start(self) -> None:
        type(self).started.set()

    async def wait(self) -> None:
        if type(self).failed is not None:
            raise type(self).failed
        await self._release.wait()

    async def stop(self) -> None:
        self._release.set()
        type(self).stopped.set()


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    _FakeCoordinator.started = asyncio.Event()
    _FakeCoordinator.stopped = asyncio.Event()
    _FakeCoordinator.failed = None


async def test_llm_failure_does_not_stop_report_coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    (tmp_path / "agent.yaml").write_text("agent:\n  enabled: true\n", encoding="utf-8")

    async def broken_llm(**_kwargs) -> None:
        raise RuntimeError("broken LLM")

    monkeypatch.setattr(module, "ReportCoordinator", _FakeCoordinator)
    monkeypatch.setattr(module, "_load_llm_runtime", lambda: broken_llm)
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_FakeCoordinator.started.wait(), timeout=1)
    await asyncio.sleep(0.05)
    assert task.done() is False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _FakeCoordinator.stopped.is_set()


async def test_synchronous_optional_import_failure_stays_report_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    (tmp_path / "agent.yaml").write_text("agent:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setattr(module, "ReportCoordinator", _FakeCoordinator)
    monkeypatch.setattr(
        module,
        "_load_llm_runtime",
        lambda: (_ for _ in ()).throw(ImportError("optional dependency missing")),
    )
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_FakeCoordinator.started.wait(), timeout=1)
    await asyncio.sleep(0)
    assert task.done() is False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _FakeCoordinator.stopped.is_set()


@pytest.mark.parametrize(
    "agent_yaml",
    [None, "agent:\n  enabled: false\n", "agent: [", "agent:\n  enabled: 'false'\n"],
    ids=["missing", "disabled", "broken", "string-false"],
)
async def test_missing_disabled_or_broken_llm_config_never_imports_optional_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_yaml: str | None,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    if agent_yaml is not None:
        (tmp_path / "agent.yaml").write_text(agent_yaml, encoding="utf-8")
    monkeypatch.setattr(module, "ReportCoordinator", _FakeCoordinator)
    monkeypatch.setattr(
        module,
        "_load_llm_runtime",
        lambda: pytest.fail("optional LLM module must not be imported"),
    )
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_FakeCoordinator.started.wait(), timeout=1)
    await asyncio.sleep(0)
    assert task.done() is False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_coordinator_failure_is_not_silently_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    _FakeCoordinator.failed = RuntimeError("coordinator died")
    monkeypatch.setattr(module, "ReportCoordinator", _FakeCoordinator)

    with pytest.raises(RuntimeError, match="coordinator died"):
        await module.run(config_dir=tmp_path, data_dir=tmp_path)

    assert _FakeCoordinator.stopped.is_set()


async def test_coordinator_start_failure_runs_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    class StartFailure(_FakeCoordinator):
        async def start(self) -> None:
            type(self).started.set()
            raise RuntimeError("start failed")

    monkeypatch.setattr(module, "ReportCoordinator", StartFailure)
    with pytest.raises(RuntimeError, match="start failed"):
        await module.run(config_dir=tmp_path, data_dir=tmp_path)
    assert StartFailure.stopped.is_set()


async def test_shutdown_allows_optional_llm_cleanup_before_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    (tmp_path / "agent.yaml").write_text("agent:\n  enabled: true\n", encoding="utf-8")
    cleaned = asyncio.Event()

    async def llm_runtime(*, shutdown_event: asyncio.Event, **_kwargs) -> None:
        await shutdown_event.wait()
        await asyncio.sleep(0)
        cleaned.set()

    monkeypatch.setattr(module, "ReportCoordinator", _FakeCoordinator)
    monkeypatch.setattr(module, "_load_llm_runtime", lambda: llm_runtime)
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_FakeCoordinator.started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleaned.is_set()
    assert _FakeCoordinator.stopped.is_set()


def test_assistant_bootstrap_import_is_report_only_and_lightweight() -> None:
    code = (
        "import sys; import cryodaq.agents.assistant_bootstrap; "
        "blocked = ('cryodaq.agents.assistant_main', 'cryodaq.reporting.generator', "
        "'cryodaq.notifications.periodic_report', 'docx', 'matplotlib', 'lancedb', "
        "'cryodaq.storage.sqlite_writer'); "
        "assert not [name for name in blocked if name in sys.modules], "
        "[name for name in blocked if name in sys.modules]"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
