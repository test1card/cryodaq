from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

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


async def test_windows_shutdown_sentinel_reaches_ordered_runtime_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    sentinel = runtime_dir / "assistant-shutdown-0123456789abcdef0123456789abcdef.signal"
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.signal, "SIGBREAK", 21, raising=False)
    signal_mock = MagicMock(return_value=object())
    monkeypatch.setattr(module.signal, "signal", signal_mock)
    monkeypatch.setenv(module._ASSISTANT_SHUTDOWN_ENV, str(sentinel))
    monkeypatch.setattr(module, "ReportCoordinator", _FakeCoordinator)

    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_FakeCoordinator.started.wait(), timeout=1)
    assert signal_mock.call_args_list[0].args[0] == 21
    assert callable(signal_mock.call_args_list[0].args[1])
    sentinel.touch()
    await asyncio.wait_for(task, timeout=1)

    assert _FakeCoordinator.stopped.is_set()


@pytest.mark.parametrize(
    "candidate_kind",
    ["symlink", "broken-symlink", "directory"],
)
def test_windows_shutdown_validation_rejects_preexisting_path_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_kind: str,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    sentinel = runtime_dir / "assistant-shutdown-0123456789abcdef0123456789abcdef.signal"
    if candidate_kind == "directory":
        sentinel.mkdir()
    else:
        target = tmp_path / ("target" if candidate_kind == "symlink" else "missing")
        if candidate_kind == "symlink":
            target.touch()
        sentinel.symlink_to(target)
    monkeypatch.setenv(module._ASSISTANT_SHUTDOWN_ENV, str(sentinel))

    with pytest.raises(RuntimeError, match="already exists"):
        module._validated_shutdown_sentinel(tmp_path)


def test_windows_shutdown_validation_rejects_link_backed_runtime_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    outside = tmp_path / "outside"
    outside.mkdir()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.symlink_to(outside, target_is_directory=True)
    sentinel = runtime_dir / "assistant-shutdown-0123456789abcdef0123456789abcdef.signal"
    monkeypatch.setenv(module._ASSISTANT_SHUTDOWN_ENV, str(sentinel))

    with pytest.raises(RuntimeError, match="runtime directory"):
        module._validated_shutdown_sentinel(tmp_path)


@pytest.mark.parametrize("candidate_kind", ["symlink", "broken-symlink", "directory"])
async def test_windows_shutdown_watcher_rejects_unsafe_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_kind: str,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    sentinel = runtime_dir / "assistant-shutdown-0123456789abcdef0123456789abcdef.signal"
    monkeypatch.setenv(module._ASSISTANT_SHUTDOWN_ENV, str(sentinel))
    authority = module._validated_shutdown_sentinel(tmp_path)
    assert authority is not None
    waiter = asyncio.create_task(module._wait_for_shutdown_sentinel(authority))
    await asyncio.sleep(0)
    if candidate_kind == "directory":
        sentinel.mkdir()
    else:
        target = tmp_path / ("target" if candidate_kind == "symlink" else "missing")
        if candidate_kind == "symlink":
            target.touch()
        sentinel.symlink_to(target)

    with pytest.raises(RuntimeError, match="unsafe assistant shutdown sentinel"):
        await asyncio.wait_for(waiter, timeout=1)


async def test_windows_shutdown_watcher_accepts_real_regular_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    sentinel = runtime_dir / "assistant-shutdown-0123456789abcdef0123456789abcdef.signal"
    monkeypatch.setenv(module._ASSISTANT_SHUTDOWN_ENV, str(sentinel))
    authority = module._validated_shutdown_sentinel(tmp_path)
    assert authority is not None
    waiter = asyncio.create_task(module._wait_for_shutdown_sentinel(authority))
    await asyncio.sleep(0)
    sentinel.touch()
    await asyncio.wait_for(waiter, timeout=1)


@pytest.mark.parametrize("replacement_kind", ["symlink", "real-directory"])
async def test_windows_shutdown_watcher_rejects_runtime_identity_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_kind: str,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    sentinel = runtime_dir / "assistant-shutdown-0123456789abcdef0123456789abcdef.signal"
    monkeypatch.setenv(module._ASSISTANT_SHUTDOWN_ENV, str(sentinel))
    authority = module._validated_shutdown_sentinel(tmp_path)
    assert authority is not None
    waiter = asyncio.create_task(module._wait_for_shutdown_sentinel(authority))
    await asyncio.sleep(0)

    original_runtime = tmp_path / "runtime-original"
    runtime_dir.rename(original_runtime)
    if replacement_kind == "symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        runtime_dir.symlink_to(outside, target_is_directory=True)
    else:
        runtime_dir.mkdir()
    sentinel.touch()

    with pytest.raises(RuntimeError, match="unsafe assistant shutdown sentinel authority"):
        await asyncio.wait_for(waiter, timeout=1)


def test_assistant_bootstrap_import_is_report_only_and_lightweight() -> None:
    code = (
        "import sys; import cryodaq.agents.assistant_bootstrap; "
        "blocked = ('cryodaq.agents.assistant_main', 'cryodaq.reporting.generator', "
        "'cryodaq.notifications.periodic_report', 'docx', 'matplotlib', 'lancedb', "
        "'cryodaq.storage.sqlite_writer', 'cryodaq.agents.assistant.periodic_png', "
        "'cryodaq.agents.assistant.periodic_runtime', "
        "'cryodaq.agents.assistant.periodic_telegram', 'zmq', 'msgpack', 'aiohttp'); "
        "assert not [name for name in blocked if name in sys.modules], "
        "[name for name in blocked if name in sys.modules]"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_assistant_main_uses_selector_event_loop_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module
    import cryodaq.logging_setup as logging_setup

    loops: list[asyncio.AbstractEventLoop] = []

    async def probe() -> None:
        loops.append(asyncio.get_running_loop())

    def forbidden_run(coroutine) -> None:
        coroutine.close()
        pytest.fail("Windows assistant entrypoint must use asyncio.Runner")

    monkeypatch.setattr(module, "run", probe)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.asyncio, "run", forbidden_run)
    monkeypatch.setattr(logging_setup, "resolve_log_level", lambda: "INFO")
    monkeypatch.setattr(logging_setup, "setup_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["cryodaq-assistant"])

    module.main()

    assert len(loops) == 1
    assert isinstance(loops[0], asyncio.SelectorEventLoop)
