from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest


class _H2:
    started = asyncio.Event()
    stopped = asyncio.Event()
    release = asyncio.Event()
    start_release: asyncio.Event | None = None
    wait_failure: BaseException | None = None
    start_failure: BaseException | None = None
    return_normally = False
    order: list[str] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def start(self) -> None:
        type(self).order.append("h2_start")
        type(self).started.set()
        if type(self).start_release is not None:
            await type(self).start_release.wait()
        if type(self).start_failure is not None:
            raise type(self).start_failure

    async def wait(self) -> None:
        type(self).order.append("h2_wait")
        if type(self).wait_failure is not None:
            raise type(self).wait_failure
        if type(self).return_normally:
            return
        await type(self).release.wait()

    async def stop(self) -> None:
        type(self).order.append("h2_stop")
        type(self).release.set()
        type(self).stopped.set()


class _H3:
    started = asyncio.Event()
    stopped = asyncio.Event()
    stop_started = asyncio.Event()
    release = asyncio.Event()
    stop_release: asyncio.Event | None = None
    failure: BaseException | None = None
    stop_failure: BaseException | None = None
    return_normally = False
    order = _H2.order
    kwargs: dict[str, object] = {}

    def __init__(self, **kwargs: object) -> None:
        type(self).kwargs = kwargs

    async def run(self) -> None:
        type(self).order.append("h3_run")
        type(self).started.set()
        if type(self).failure is not None:
            raise type(self).failure
        if type(self).return_normally:
            return
        await type(self).release.wait()

    async def stop(self) -> None:
        type(self).order.append("h3_stop")
        type(self).stop_started.set()
        if type(self).stop_release is not None:
            await type(self).stop_release.wait()
        type(self).release.set()
        type(self).stopped.set()
        if type(self).stop_failure is not None:
            raise type(self).stop_failure


@pytest.fixture(autouse=True)
def _reset_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    _H2.started = asyncio.Event()
    _H2.stopped = asyncio.Event()
    _H2.release = asyncio.Event()
    _H2.start_release = None
    _H2.wait_failure = None
    _H2.start_failure = None
    _H2.return_normally = False
    _H2.order = []
    _H3.started = asyncio.Event()
    _H3.stopped = asyncio.Event()
    _H3.stop_started = asyncio.Event()
    _H3.release = asyncio.Event()
    _H3.stop_release = None
    _H3.failure = None
    _H3.stop_failure = None
    _H3.return_normally = False
    _H3.order = _H2.order
    _H3.kwargs = {}
    monkeypatch.setenv("CRYODAQ_ASSISTANT_EXPERIMENT_MODE", "1")


def _install_h3(module: Any, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    factory_calls: list[dict[str, object]] = []

    def factory_builder(**kwargs: object) -> object:
        factory_calls.append(kwargs)
        return object()

    monkeypatch.setattr(module, "_load_periodic_runtime", lambda: (_H3, factory_builder))
    return factory_calls


@pytest.mark.parametrize("value", [None, "0", "true", "01", " 1", "secret-value"])
async def test_exact_off_never_loads_or_constructs_h3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    value: str | None,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    if value is None:
        monkeypatch.delenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", raising=False)
    else:
        monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", value)
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    monkeypatch.setattr(
        module,
        "_load_periodic_runtime",
        lambda: pytest.fail("exact-off path imported H3 runtime"),
    )
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_H2.started.wait(), timeout=1)
    assert not _H3.started.is_set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    if value not in {None, "0"}:
        assert "Invalid assistant periodic-mode flag" in caplog.text
        assert value not in caplog.text


async def test_exact_on_builds_one_critical_h3_with_fixed_paths_and_stops_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    calls = _install_h3(module, monkeypatch)
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_H3.started.wait(), timeout=1)
    assert calls == [{"data_dir": tmp_path, "archive_dir": tmp_path / "archive"}]
    assert _H3.kwargs["periodic_allowed"] is True
    assert _H3.kwargs["data_dir"] == tmp_path
    assert _H3.kwargs["config_dir"] == tmp_path
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _H3.order.index("h3_stop") < _H3.order.index("h2_stop")
    assert _H3.stopped.is_set() and _H2.stopped.is_set()


@pytest.mark.parametrize("normal", [False, True], ids=["exception", "normal-return"])
async def test_h3_exception_or_normal_return_is_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    normal: bool,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    _install_h3(module, monkeypatch)
    if normal:
        _H3.return_normally = True
        expected = "periodic PNG supervisor stopped unexpectedly"
    else:
        _H3.failure = RuntimeError("h3 died")
        expected = "h3 died"
    with pytest.raises(RuntimeError, match=expected):
        await module.run(config_dir=tmp_path, data_dir=tmp_path)
    assert _H3.stopped.is_set() and _H2.stopped.is_set()


async def test_h2_failure_uses_global_teardown_and_stops_h3_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    _install_h3(module, monkeypatch)
    _H2.wait_failure = RuntimeError("h2 died")
    with pytest.raises(RuntimeError, match="h2 died"):
        await module.run(config_dir=tmp_path, data_dir=tmp_path)
    assert _H3.order.index("h3_stop") < _H3.order.index("h2_stop")


async def test_h2_normal_monitor_return_is_fixed_fatal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    _H2.return_normally = True
    with pytest.raises(RuntimeError, match="automatic report coordinator stopped unexpectedly"):
        await module.run(config_dir=tmp_path, data_dir=tmp_path)
    assert _H2.stopped.is_set()


async def test_optional_llm_failure_does_not_stop_h3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    (tmp_path / "agent.yaml").write_text("agent:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    _install_h3(module, monkeypatch)

    async def broken_llm(**_kwargs: object) -> None:
        raise RuntimeError("optional failure")

    monkeypatch.setattr(module, "_load_llm_runtime", lambda: broken_llm)
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_H3.started.wait(), timeout=1)
    await asyncio.sleep(0)
    assert not task.done()
    assert not _H3.stopped.is_set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_llm_replay_lane_remains_independent_while_h3_is_exact_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    (tmp_path / "agent.yaml").write_text("agent:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "0")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    monkeypatch.setattr(
        module,
        "_load_periodic_runtime",
        lambda: pytest.fail("replay exact-off path loaded H3"),
    )
    llm_started = asyncio.Event()

    async def llm(*, shutdown_event: asyncio.Event, **_kwargs: object) -> None:
        llm_started.set()
        await shutdown_event.wait()

    monkeypatch.setattr(module, "_load_llm_runtime", lambda: llm)
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(llm_started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_repeated_cancellation_waits_for_delayed_h3_stop_before_h2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    _install_h3(module, monkeypatch)
    _H3.stop_release = asyncio.Event()
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_H3.started.wait(), timeout=1)
    task.cancel()
    await asyncio.wait_for(_H3.stop_started.wait(), timeout=1)
    task.cancel()
    await asyncio.sleep(0)
    assert not _H2.stopped.is_set()
    _H3.stop_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _H3.stopped.is_set() and _H2.stopped.is_set()


async def test_h3_stop_failure_still_cleans_h2_llm_and_all_signal_handlers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    (tmp_path / "agent.yaml").write_text("agent:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    _install_h3(module, monkeypatch)
    _H3.stop_failure = RuntimeError("h3 stop failed")
    llm_cleaned = asyncio.Event()

    async def llm(*, shutdown_event: asyncio.Event, **_kwargs: object) -> None:
        await shutdown_event.wait()
        llm_cleaned.set()

    monkeypatch.setattr(module, "_load_llm_runtime", lambda: llm)
    loop = asyncio.get_running_loop()
    added: list[int] = []
    removed: list[int] = []
    monkeypatch.setattr(loop, "add_signal_handler", lambda signum, _callback: added.append(signum))
    monkeypatch.setattr(loop, "remove_signal_handler", lambda signum: removed.append(signum) or True)
    monkeypatch.setattr(module.sys, "platform", "test-platform")

    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_H3.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert _H2.stopped.is_set() and llm_cleaned.is_set()
    assert added and removed == added


async def test_h2_constructor_failure_precedes_signal_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    class ConstructorFailure:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("constructor failed")

    monkeypatch.setattr(module, "ReportCoordinator", ConstructorFailure)
    monkeypatch.setattr(
        module.asyncio,
        "get_running_loop",
        lambda: pytest.fail("signal installation reached after constructor failure"),
    )
    with pytest.raises(RuntimeError, match="constructor failed"):
        await module.run(config_dir=tmp_path, data_dir=tmp_path)


async def test_cancellation_during_h2_start_still_stops_h2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.signal, "SIGBREAK", 21, raising=False)
    monkeypatch.setattr(module.signal, "signal", lambda _signum, _handler: object())
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    _H2.start_release = asyncio.Event()
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_H2.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _H2.stopped.is_set()


async def test_windows_sigbreak_requests_orderly_shutdown_and_restores_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    previous = object()
    calls: list[tuple[int, object]] = []

    def install(signum: int, handler: object) -> object:
        calls.append((signum, handler))
        return previous

    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.signal, "SIGBREAK", 21, raising=False)
    monkeypatch.setattr(module.signal, "signal", install)
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_H2.started.wait(), timeout=1)
    assert len(calls) == 1

    handler = calls[0][1]
    assert callable(handler)
    handler(21, None)
    await asyncio.wait_for(task, timeout=1)

    assert _H2.stopped.is_set()
    assert calls[1] == (21, previous)


async def test_windows_sigbreak_install_failure_precedes_runtime_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.signal, "SIGBREAK", 21, raising=False)
    monkeypatch.setattr(
        module.signal,
        "signal",
        lambda _signum, _handler: (_ for _ in ()).throw(RuntimeError("SIGBREAK install failed")),
    )
    monkeypatch.setattr(module, "ReportCoordinator", _H2)

    with pytest.raises(RuntimeError, match="SIGBREAK install failed"):
        await module.run(config_dir=tmp_path, data_dir=tmp_path)
    assert not _H2.started.is_set()


async def test_synchronous_h3_construction_failure_rolls_back_h2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)

    class BrokenH3:
        def __init__(self, **_kwargs: object) -> None:
            raise RuntimeError("h3 construction failed")

    monkeypatch.setattr(module, "_load_periodic_runtime", lambda: (BrokenH3, lambda **_kwargs: object()))
    with pytest.raises(RuntimeError, match="h3 construction failed"):
        await module.run(config_dir=tmp_path, data_dir=tmp_path)
    assert _H2.stopped.is_set()


async def test_start_order_is_h2_monitor_then_one_h3_then_optional_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    (tmp_path / "agent.yaml").write_text("agent:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    _install_h3(module, monkeypatch)
    llm_started = asyncio.Event()

    async def llm(*, shutdown_event: asyncio.Event, **_kwargs: object) -> None:
        _H2.order.append("llm_run")
        llm_started.set()
        await shutdown_event.wait()

    monkeypatch.setattr(module, "_load_llm_runtime", lambda: llm)
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_H3.started.wait(), timeout=1)
    await asyncio.wait_for(llm_started.wait(), timeout=1)
    assert _H2.order[:4] == ["h2_start", "h2_wait", "h3_run", "llm_run"]
    assert _H2.order.count("h3_run") == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_h3_only_mode_runs_without_h2_monitor_or_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setenv("CRYODAQ_ASSISTANT_EXPERIMENT_MODE", "0")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    _install_h3(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "_load_llm_runtime",
        lambda: pytest.fail("LLM must remain disabled"),
    )
    task = asyncio.create_task(module.run(config_dir=tmp_path, data_dir=tmp_path))
    await asyncio.wait_for(_H3.started.wait(), timeout=1)
    await asyncio.sleep(0)
    assert not task.done()
    assert "h2_wait" not in _H2.order
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_partial_signal_registration_failure_rolls_back_installed_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    monkeypatch.setattr(module.sys, "platform", "test-platform")
    loop = asyncio.get_running_loop()
    added: list[int] = []
    removed: list[int] = []

    def add(signum: int, _callback: object) -> None:
        if added:
            raise RuntimeError("second signal failed")
        added.append(signum)

    monkeypatch.setattr(loop, "add_signal_handler", add)
    monkeypatch.setattr(
        loop,
        "remove_signal_handler",
        lambda signum: removed.append(signum) or True,
    )
    with pytest.raises(RuntimeError, match="second signal failed"):
        await module.run(config_dir=tmp_path, data_dir=tmp_path)
    assert removed == added
    assert not _H2.started.is_set()


async def test_partial_signal_rollback_failure_is_chained_to_add_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant_bootstrap as module

    monkeypatch.setattr(module, "ReportCoordinator", _H2)
    monkeypatch.setattr(module.sys, "platform", "test-platform")
    loop = asyncio.get_running_loop()
    added: list[int] = []

    def add(signum: int, _callback: object) -> None:
        if added:
            raise RuntimeError("signal add failed")
        added.append(signum)

    monkeypatch.setattr(loop, "add_signal_handler", add)
    monkeypatch.setattr(
        loop,
        "remove_signal_handler",
        lambda _signum: (_ for _ in ()).throw(RuntimeError("signal remove failed")),
    )
    with pytest.raises(RuntimeError, match="signal add failed") as caught:
        await module.run(config_dir=tmp_path, data_dir=tmp_path)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "signal remove failed" in str(caught.value.__cause__)


async def test_inner_cleanup_task_cancellation_is_not_outer_cancellation() -> None:
    import cryodaq.agents.assistant_bootstrap as module

    task = asyncio.create_task(asyncio.sleep(60))
    task.cancel()
    outer, inner = await module._settle_cleanup_task(task)
    assert outer is None
    assert isinstance(inner, asyncio.CancelledError)
