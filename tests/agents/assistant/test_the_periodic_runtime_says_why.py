"""Production-path guards for periodic runtime failure diagnostics."""

from __future__ import annotations

import asyncio
import logging

import pytest

from cryodaq.agents.assistant import periodic_png
from cryodaq.periodic_state import load_periodic_state, set_periodic_health, write_periodic_state


class _Clock:
    def __init__(self) -> None:
        self.monotonic_value = 1000.0

    def monotonic(self) -> float:
        return self.monotonic_value

    def wall_time(self) -> float:
        return 1_700_000_000.0

    def display_time(self, epoch: int) -> str:
        return str(epoch)


def _supervisor(tmp_path, factory):
    clock = _Clock()
    supervisor = periodic_png.PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path / "config",
        periodic_allowed=True,
        coordinator_factory=factory,
        clock=clock,
    )

    async def _run_blocking(func, *args, **kwargs):
        return func(*args, **kwargs)

    supervisor._run_blocking = _run_blocking
    return supervisor, clock


def test_the_production_failure_branches_persist_distinct_labels(tmp_path) -> None:
    """The loader and construction paths must leave distinguishable durable reasons."""

    loader, _clock = _supervisor(tmp_path / "loader", lambda _config: pytest.fail("factory must not run"))
    loader._config_dir = "api.telegram.org/bot-config"
    loader._leader_fd = 1
    loader._release_leader = lambda: None

    async def _sleep_or_stop(_seconds: float) -> None:
        return None

    loader._sleep_or_stop = _sleep_or_stop
    asyncio.run(loader._handle_config_loader_failure(0, ValueError("bad yaml")))
    loader_text = load_periodic_state(tmp_path / "loader").payload["health"]["error_text"]
    assert "configuration could not be loaded" in loader_text
    assert "api.telegram.org/bot" not in loader_text
    assert "<telegram-url-removed>" in loader_text

    def _construction_fails(_config):
        raise ValueError("bad yaml")

    constructed, _clock = _supervisor(tmp_path / "constructed", _construction_fails)
    assert not asyncio.run(constructed._try_construct_and_start(object()))
    construction_text = load_periodic_state(tmp_path / "constructed").payload["health"]["error_text"]
    assert "coordinator could not be constructed" in construction_text
    assert loader_text != construction_text


def test_a_credential_bearing_exception_is_persisted_safely_by_the_production_writer(tmp_path) -> None:
    token = "bot7701234567:AAEhBPqZxYvUtSrQpOnMlKjIhGfEdCbA9"
    cause = RuntimeError(f"POST https://api.telegram.org/{token}/sendPhoto failed with 401")
    supervisor, _clock = _supervisor(tmp_path, lambda _config: pytest.fail("factory must not run"))

    asyncio.run(supervisor._write_runtime_failed_health(cause, because="the coordinator could not be constructed"))

    health = load_periodic_state(tmp_path).payload["health"]
    assert health["error_code"] == "periodic_runtime_failed"
    assert token not in health["error_text"]
    assert "api.telegram.org/bot" not in health["error_text"]
    assert "<telegram-url-removed>" in health["error_text"]
    assert "401" in health["error_text"]


def test_an_unrenderable_exception_still_replaces_stale_health(tmp_path) -> None:
    class _UnrenderableError(RuntimeError):
        def __str__(self) -> str:
            raise RuntimeError("rendering failed")

    state = load_periodic_state(tmp_path)
    starting = set_periodic_health(state, status="starting", code=None, text="", now=1.0)
    write_periodic_state(tmp_path, starting)
    supervisor, _clock = _supervisor(tmp_path, lambda _config: pytest.fail("factory must not run"))

    asyncio.run(supervisor._write_runtime_failed_health(_UnrenderableError()))

    health = load_periodic_state(tmp_path).payload["health"]
    assert health["status"] == "degraded_runtime"
    assert health["error_code"] == "periodic_runtime_failed"
    assert "_UnrenderableError" in health["error_text"]


def test_a_very_long_exception_cannot_fill_the_health_record() -> None:
    text = periodic_png._runtime_failed_text(RuntimeError("x" * 5000), "construction failed")
    assert len(text) <= periodic_png._RUNTIME_REASON_MAX_CHARS
    assert text.endswith("\u2026")


def test_production_writer_replaces_invalid_unicode_in_failure_reasons(tmp_path) -> None:
    state = load_periodic_state(tmp_path)
    ready = set_periodic_health(state, status="ready", code=None, text="", now=1.0)
    write_periodic_state(tmp_path, ready)
    supervisor, _clock = _supervisor(tmp_path, lambda _config: pytest.fail("factory must not run"))

    asyncio.run(supervisor._write_runtime_failed_health(RuntimeError("bad surrogate: \ud800")))

    health = load_periodic_state(tmp_path).payload["health"]
    assert health["status"] == "degraded_runtime"
    assert health["error_code"] == "periodic_runtime_failed"
    assert "bad surrogate" in health["error_text"]
    health["error_text"].encode("utf-8", errors="strict")


def test_production_writer_bounds_long_whitespace_free_failure_reasons(tmp_path, monkeypatch) -> None:
    observed_lengths: list[int] = []

    class Locator:
        def sub(self, replacement: str, value: str) -> str:
            observed_lengths.append(len(value))
            return value

    monkeypatch.setattr(periodic_png, "_PROHIBITED_LOCATOR", Locator())
    supervisor, _clock = _supervisor(tmp_path, lambda _config: pytest.fail("factory must not run"))

    asyncio.run(supervisor._write_runtime_failed_health(RuntimeError("x" * 100_000)))

    health = load_periodic_state(tmp_path).payload["health"]
    assert health["status"] == "degraded_runtime"
    assert len(health["error_text"]) <= periodic_png._RUNTIME_REASON_MAX_CHARS
    assert max(observed_lengths) == periodic_png._RUNTIME_REASON_MAX_CHARS * 16


@pytest.mark.parametrize(
    ("persisted_code", "preserved"),
    [
        ("periodic_live_source_stopped", True),
        ("periodic_projection_incomplete", False),
        ("periodic_tls_verification_disabled", False),
        ("periodic_runtime_failed", False),
        (None, False),
    ],
)
def test_monitor_failure_orchestration_preserves_only_live_source_health(
    tmp_path, caplog, persisted_code, preserved
) -> None:
    if persisted_code is not None:
        state = load_periodic_state(tmp_path)
        candidate = set_periodic_health(
            state,
            status="degraded_source" if persisted_code != "periodic_runtime_failed" else "degraded_runtime",
            code=persisted_code,
            text="something the monitor or an earlier step wrote",
            now=1.0,
        )
        write_periodic_state(tmp_path, candidate)

    supervisor, _clock = _supervisor(tmp_path, lambda _config: pytest.fail("factory must not run"))
    with caplog.at_level(logging.ERROR, logger=periodic_png.__name__):
        asyncio.run(supervisor._stop_then_keep_monitor_health())

    health = load_periodic_state(tmp_path).payload["health"]
    if preserved:
        assert health["error_code"] == "periodic_live_source_stopped"
        assert "live-source monitor stopped the coordinator" in caplog.records[-1].getMessage()
    else:
        assert health["error_code"] == "periodic_runtime_failed"
        assert "monitor reported a failure" in health["error_text"]


def test_alternating_persisting_failures_are_limited_per_signature(caplog, tmp_path) -> None:
    supervisor, clock = _supervisor(tmp_path, lambda _config: pytest.fail("factory must not run"))

    with caplog.at_level(logging.ERROR, logger=periodic_png.__name__):
        for _ in range(10):
            supervisor._log_runtime_failure("the monitor reported a failure", None)
            clock.monotonic_value += 1.0
            supervisor._log_runtime_failure("the configuration changed", None)
            clock.monotonic_value += 1.0
        assert len(caplog.records) == 2

        clock.monotonic_value += periodic_png._RUNTIME_FAILED_LOG_INTERVAL_S
        supervisor._log_runtime_failure("the monitor reported a failure", None)
        supervisor._log_runtime_failure("the configuration changed", None)
        assert len(caplog.records) == 4


def test_every_runtime_failure_entry_point_is_rate_limited(caplog, tmp_path) -> None:
    """Repeated production failures must not open a second logging door."""

    async def _sleep_or_stop(_seconds: float) -> None:
        return None

    loader, _clock = _supervisor(tmp_path / "loader", lambda _config: pytest.fail("factory must not run"))
    loader._leader_fd = None
    loader._sleep_or_stop = _sleep_or_stop

    def _construction_fails(_config):
        raise ValueError("bad yaml")

    constructed, _clock = _supervisor(tmp_path / "constructed", _construction_fails)
    writer, _clock = _supervisor(tmp_path / "writer", lambda _config: pytest.fail("factory must not run"))
    monitor, _clock = _supervisor(tmp_path / "monitor", lambda _config: pytest.fail("factory must not run"))
    state = load_periodic_state(tmp_path / "monitor")
    write_periodic_state(
        tmp_path / "monitor",
        set_periodic_health(
            state,
            status="degraded_source",
            code="periodic_live_source_stopped",
            text="the live source stopped",
            now=1.0,
        ),
    )

    with caplog.at_level(logging.ERROR, logger=periodic_png.__name__):
        for _ in range(2):
            asyncio.run(loader._handle_config_loader_failure(0, ValueError("bad yaml")))
            assert not asyncio.run(constructed._try_construct_and_start(object()))
            asyncio.run(writer._write_runtime_failed_health(ValueError("bad yaml"), because="writer failed"))
            asyncio.run(monitor._stop_then_keep_monitor_health())

    assert len(caplog.records) == 4


def test_the_module_can_be_heard_at_all() -> None:
    assert isinstance(periodic_png._log, logging.Logger)
    assert periodic_png._log.name == periodic_png.__name__
