from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from types import ModuleType

import pytest

from cryodaq.agents.assistant.periodic_delivery import (
    PeriodicDeliveryContext,
    PeriodicDeliveryOutcome,
    PeriodicDeliveryReceipt,
    PeriodicDeliveryResult,
)
from cryodaq.agents.assistant.periodic_png import (
    AlarmQueryResult,
    LiveSourceCut,
    PeriodicPngCoordinator,
    PeriodicPngSupervisor,
)
from cryodaq.agents.assistant.periodic_telegram import TelegramDeliveryResult, TelegramOutcome
from cryodaq.notifications._secrets import SecretStr
from cryodaq.periodic_config import PeriodicPngConfig, PeriodicPngConfigLoad
from cryodaq.periodic_state import (
    PeriodicArtifact,
    load_periodic_state,
    periodic_telegram_destination_fingerprint,
)
from cryodaq.report_process import (
    PeriodicRenderResult,
    ReportProcessError,
    ReportProcessRunner,
    read_periodic_artifact_bytes,
)
from cryodaq.storage.archive_reader import (
    ArchiveReader,
    BoundedReadingQueryResult,
    BoundedReadingRow,
)

ENGINE = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "engine.py"
DESTINATION_FINGERPRINT = periodic_telegram_destination_fingerprint(-100123)


def _install_windows_signal_double(
    bootstrap: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[int, object]:
    """Provide the SIGBREAK API that exists on Windows but not the test host."""

    sigbreak = 21
    handlers: dict[int, object] = {sigbreak: bootstrap.signal.SIG_DFL}
    original_signal = bootstrap.signal.signal

    def set_handler(signum: int, handler: object) -> object:
        if signum != sigbreak:
            return original_signal(signum, handler)
        previous = handlers[signum]
        handlers[signum] = handler
        return previous

    monkeypatch.setattr(bootstrap.signal, "SIGBREAK", sigbreak, raising=False)
    monkeypatch.setattr(bootstrap.signal, "signal", set_handler)
    return handlers


def _config() -> PeriodicPngConfig:
    return PeriodicPngConfig(
        enabled=True,
        interval_s=60,
        chart_window_s=120,
        include_channels=None,
        max_points_per_channel=100,
        max_total_points=200,
        max_input_bytes=65_536,
        render_timeout_s=5.0,
        max_render_attempts=2,
        max_delivery_attempts=2,
        backoff_base_s=1.0,
        backoff_cap_s=8.0,
        telegram_token=SecretStr("123456:abcdefghijklmnopqrstuvwxyz"),
        telegram_chat_id=-100123,
        telegram_timeout_s=2.0,
        telegram_verify_ssl=True,
        config_fingerprint="sha256:" + "c" * 64,
    )


def _engine_tree() -> ast.Module:
    return ast.parse(ENGINE.read_text(encoding="utf-8"))


def _notifications(*, enabled: bool) -> str:
    return (
        "telegram:\n"
        "  bot_token: '123456:abcdefghijklmnopqrstuvwxyzABCDE'\n"
        "  chat_id: -100123\n"
        "  timeout_s: 10\n"
        "  verify_ssl: true\n"
        "  send_cleared: true\n"
        "periodic_report:\n"
        f"  enabled: {'true' if enabled else 'false'}\n"
        "  report_interval_s: 3600\n"
        "commands:\n"
        "  enabled: false\n"
    )


def _agent(*, enabled: bool) -> str:
    return f"agent:\n  enabled: {'true' if enabled else 'false'}\nreporting:\n  automatic_enabled: false\n"


def test_engine_has_zero_legacy_import_reference_constructor_or_lifecycle() -> None:
    tree = _engine_tree()
    forbidden_names = {"PeriodicReporter", "periodic_reporter"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_names
        if isinstance(node, ast.ImportFrom):
            assert node.module != "cryodaq.notifications.periodic_report"
        if isinstance(node, ast.Import):
            assert all(alias.name != "cryodaq.notifications.periodic_report" for alias in node.names)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "cryodaq.notifications.periodic_report" not in node.value


def test_fresh_engine_import_excludes_legacy_and_renderer_stacks() -> None:
    code = (
        "import sys; import cryodaq.engine; "
        "blocked = ('cryodaq.notifications.periodic_report', 'matplotlib', "
        "'matplotlib.pyplot', 'docx', 'cryodaq.reporting.periodic_renderer'); "
        "assert not [name for name in blocked if name in sys.modules], "
        "[name for name in blocked if name in sys.modules]"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_legacy_module_remains_importable_as_dead_characterization() -> None:
    from cryodaq.notifications.periodic_report import PeriodicReporter

    reporter = PeriodicReporter(
        object(),
        object(),
        bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDE",
        chat_id=-100123,
    )
    assert reporter._collect_task is None
    assert reporter._report_task is None


def test_real_h3_factory_builds_fixed_resource_free_private_graph(tmp_path: Path) -> None:
    from cryodaq.agents.assistant import periodic_runtime

    archive_dir = tmp_path / "archive"
    factory = periodic_runtime.make_periodic_coordinator_factory(
        data_dir=tmp_path,
        archive_dir=archive_dir,
    )
    coordinator = factory(_config())

    assert type(coordinator) is PeriodicPngCoordinator
    assert coordinator._data_dir == tmp_path
    assert type(coordinator._live) is periodic_runtime.SequencedPeriodicLiveSources
    assert type(coordinator._live._query) is periodic_runtime.PeriodicEngineQuery
    assert coordinator._live._address == "tcp://127.0.0.1:5555"
    assert coordinator._live._query._address == "tcp://127.0.0.1:5556"
    assert coordinator._alarm_query._query is coordinator._live._query
    assert type(coordinator._archive_query.__self__) is ArchiveReader
    assert coordinator._archive_query.__self__._data_dir == tmp_path
    assert coordinator._archive_query.__self__._archive_dir == archive_dir
    assert type(coordinator._runner) is ReportProcessRunner
    assert coordinator._runner._data_dir == tmp_path.resolve()
    assert type(coordinator._delivery) is periodic_runtime._TelegramPeriodicDelivery

    # Construction is intentionally inert: no socket/context, HTTP session,
    # child, background task, or runtime-state hierarchy exists before start.
    assert coordinator._live._context is None
    assert coordinator._live._socket is None
    assert coordinator._live._receive_task is None
    assert coordinator._delivery._client._transport._session is None
    assert coordinator._loop_task is None
    assert coordinator._live_task is None
    assert not (tmp_path / "reporting").exists()


async def _run_bootstrap_h3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    destination: list[bytes],
    lifecycle: list[str] | None = None,
    fail_before_send: bool = False,
) -> None:
    import cryodaq.agents.assistant_bootstrap as bootstrap

    class H2:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    class H3:
        def __init__(self, **_kwargs: object) -> None:
            if lifecycle is not None:
                lifecycle.append("construct")

        async def run(self) -> None:
            if lifecycle is not None:
                lifecycle.append("run")
            if fail_before_send:
                raise RuntimeError("h3 readiness failed")
            destination.append(b"one-periodic-png")

        async def stop(self) -> None:
            if lifecycle is not None:
                lifecycle.append("stop")

    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    windows_handlers = _install_windows_signal_double(bootstrap, monkeypatch)
    monkeypatch.setattr(bootstrap, "ReportCoordinator", H2)
    monkeypatch.setattr(
        bootstrap,
        "_load_periodic_runtime",
        lambda: (H3, lambda **_kwargs: object()),
    )
    try:
        await bootstrap.run(config_dir=tmp_path, data_dir=tmp_path)
    finally:
        assert windows_handlers[21] == bootstrap.signal.SIG_DFL


async def test_enabled_live_bootstrap_constructs_and_runs_exactly_one_h3_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.paths
    from cryodaq.launcher import _assistant_runtime_decision

    (tmp_path / "agent.yaml").write_text(_agent(enabled=False), encoding="utf-8")
    (tmp_path / "notifications.yaml").write_text(_notifications(enabled=True), encoding="utf-8")
    monkeypatch.setattr(cryodaq.paths, "get_config_dir", lambda: tmp_path)
    required, periodic = _assistant_runtime_decision(experiment_mode=True)
    assert required and periodic
    monkeypatch.setenv("CRYODAQ_ASSISTANT_EXPERIMENT_MODE", "1")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    destination: list[bytes] = []
    lifecycle: list[str] = []
    with pytest.raises(RuntimeError, match="periodic PNG supervisor stopped unexpectedly"):
        await _run_bootstrap_h3(
            tmp_path,
            monkeypatch,
            destination=destination,
            lifecycle=lifecycle,
        )
    assert destination == [b"one-periodic-png"]
    assert lifecycle == ["construct", "run", "stop"]


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _immutable_png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 640, 480, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", b"h3-cutover-proof")
        + _png_chunk(b"IEND", b"")
    )


class _CompositionClock:
    def __init__(self) -> None:
        self._wall = 59.0
        self._revision = 0
        self._waiters = 0
        self._condition = asyncio.Condition()

    def wall_time(self) -> float:
        return self._wall

    def monotonic(self) -> float:
        return 0.0

    def display_time(self, _epoch: int) -> str:
        return "01.01.1970 00:03"

    async def sleep(self, _seconds: float) -> None:
        async with self._condition:
            revision = self._revision
            self._waiters += 1
            self._condition.notify_all()
            try:
                await self._condition.wait_for(lambda: self._revision != revision)
            finally:
                self._waiters -= 1
                self._condition.notify_all()

    async def wait_until_idle(self, owners: int) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: self._waiters >= owners)

    async def advance_to(self, wall: float) -> None:
        async with self._condition:
            self._wall = wall
            self._revision += 1
            self._condition.notify_all()


def _cut(sequence: int) -> LiveSourceCut:
    return LiveSourceCut(
        session_id="a" * 32,
        generation=1,
        sequence=sequence,
        published_at=120.0 + sequence,
        reading_drop_count=0,
        publish_failure_count=0,
        alarm_state_revision=1,
        alarm_state_token="sha256:" + "d" * 64,
    )


class _CompositionLive:
    def __init__(self) -> None:
        self._cuts = [_cut(1), _cut(2), _cut(3), _cut(4)]
        self._done = asyncio.Event()
        self.starts = 0
        self.stops = 0

    async def start(self, _on_reading: object, _on_event: object) -> None:
        self.starts += 1

    async def ready(self) -> LiveSourceCut:
        return self._cuts.pop(0) if self._cuts else _cut(10)

    def complete_since(self, _cut_value: LiveSourceCut) -> bool:
        return True

    async def wait(self) -> None:
        await self._done.wait()

    async def stop(self) -> None:
        self.stops += 1
        self._done.set()


class _CompositionQuery:
    def __init__(self) -> None:
        self.closed = 0

    async def alarm_snapshot(self) -> AlarmQueryResult:
        return AlarmQueryResult(
            ok=True,
            payload={"ok": True, "active": {}},
            state_token="sha256:" + "d" * 64,
            state_revision=1,
            error_code=None,
        )

    async def close(self) -> None:
        self.closed += 1


class _CompositionArchive:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, **_kwargs: object) -> BoundedReadingQueryResult:
        self.calls += 1
        return BoundedReadingQueryResult(
            rows=(BoundedReadingRow(100.0, "ls", "T", 1.0, "K", "ok"),),
            complete=True,
            truncated=False,
            issues=(),
            issue_overflow=0,
            discovered_channels=("T",),
            rows_examined=1,
            rows_dropped_by_caps=0,
            retained_encoded_bytes=32,
        )


class _CompositionRunner:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self.calls = 0

    def recover_periodic(self, *_args: object, **_kwargs: object) -> None:
        return None

    def generate_periodic(
        self,
        generation_id: str,
        **_kwargs: object,
    ) -> PeriodicRenderResult:
        self.calls += 1
        active = load_periodic_state(self._data_dir).payload["active"]
        assert isinstance(active, dict)
        raw = _immutable_png()
        root = self._data_dir / "reporting" / "periodic"
        staging_parent = root / ".staging"
        generations_parent = root / "generations"
        staging_parent.mkdir(parents=True)
        generations_parent.mkdir(parents=True)
        staging = staging_parent / generation_id
        staging.mkdir()
        artifact = PeriodicArtifact(
            path=f"periodic/generations/{generation_id}/periodic.png",
            sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
            size=len(raw),
            width=640,
            height=480,
            mime="image/png",
        )
        result = PeriodicRenderResult(
            generation_id=generation_id,
            owner_token=str(active["owner_token"]),
            slot_id=str(active["slot_id"]),
            config_fingerprint=str(active["config_fingerprint"]),
            artifact=artifact,
            caption="immutable H3 cutover proof",
        )
        (staging / "periodic.png").write_bytes(raw)
        (staging / "result.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "ok": True,
                    "generation_id": generation_id,
                    "owner_token": result.owner_token,
                    "slot_id": result.slot_id,
                    "config_fingerprint": result.config_fingerprint,
                    "artifact": {
                        "path": artifact.path,
                        "sha256": artifact.sha256,
                        "size": artifact.size,
                        "width": artifact.width,
                        "height": artifact.height,
                        "mime": artifact.mime,
                    },
                    "caption": result.caption,
                    "error_code": None,
                    "error_text": "",
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        os.rename(staging, generations_parent / generation_id)
        return result


class _DiagnosticArtifactReader:
    """Retain bounded evidence without replacing the production reader."""

    def __init__(self) -> None:
        self.failures: list[tuple[str, str]] = []

    def __call__(self, data_dir: Path, artifact: PeriodicArtifact) -> bytes:
        try:
            return read_periodic_artifact_bytes(data_dir, artifact)
        except ReportProcessError as exc:
            self.failures.append((exc.error_code, exc.error_text))
            raise
        except Exception as exc:
            self.failures.append((type(exc).__name__, str(exc)[:512]))
            raise


class _CompositionTelegram:
    def __init__(self) -> None:
        self.deliveries: list[tuple[bytes, str]] = []
        self.sent = asyncio.Event()
        self.closed = 0

    async def send_photo(self, photo: bytes, caption: str) -> TelegramDeliveryResult:
        assert type(photo) is bytes
        self.deliveries.append((photo, caption))
        self.sent.set()
        return TelegramDeliveryResult(
            TelegramOutcome.ACCEPTED,
            77,
            200,
            None,
            None,
            "",
        )

    async def send_artifact(
        self,
        photo: bytes,
        caption: str,
        _context: PeriodicDeliveryContext,
    ) -> PeriodicDeliveryResult:
        result = await self.send_photo(photo, caption)
        return PeriodicDeliveryResult(
            PeriodicDeliveryOutcome.ACCEPTED,
            PeriodicDeliveryReceipt("telegram", str(result.message_id), None),
            False,
            None,
            None,
            "",
        )

    async def close(self) -> None:
        self.closed += 1


async def test_real_supervisor_and_coordinator_deliver_one_due_slot_without_legacy(
    tmp_path: Path,
) -> None:
    from cryodaq.agents.assistant import periodic_runtime

    legacy_before = sys.modules.get("cryodaq.notifications.periodic_report")
    config = _config()
    clock = _CompositionClock()
    live = _CompositionLive()
    query = _CompositionQuery()
    archive = _CompositionArchive()
    runner = _CompositionRunner(tmp_path)
    telegram = _CompositionTelegram()
    artifact_reader = _DiagnosticArtifactReader()
    constructed: list[PeriodicPngCoordinator] = []

    def coordinator_factory(observed: PeriodicPngConfig) -> PeriodicPngCoordinator:
        assert observed is config
        coordinator = PeriodicPngCoordinator(
            data_dir=tmp_path,
            config=observed,
            live_sources=live,
            alarm_query=periodic_runtime._PeriodicAlarmAdapter(query),
            archive_query=archive,
            runner=runner,
            delivery=telegram,
            destination_fingerprint=DESTINATION_FINGERPRINT,
            expected_delivery_kind="telegram",
            artifact_reader=artifact_reader,
            clock=clock,
            generation_factory=lambda: "4" * 32,
            owner_factory=lambda: "5" * 32,
        )
        constructed.append(coordinator)
        return coordinator

    def config_loader(_config_dir: Path) -> PeriodicPngConfigLoad:
        return PeriodicPngConfigLoad(
            selected_path=None,
            requested=True,
            runnable=True,
            config=config,
            error_code=None,
            error_text="",
        )

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=coordinator_factory,
        config_loader=config_loader,
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    try:
        try:
            # Start below the first due slot, then wait until both the real
            # coordinator and supervisor have reached their idle boundaries.
            # The fast multi-slot jump is deterministic on slow Windows and
            # cannot race coordinator startup or artifact authorization.
            await asyncio.wait_for(clock.wait_until_idle(2), timeout=3.0)
            assert len(constructed) == 1
            assert live.starts == 1
            assert constructed[0]._loop_task is not None
            assert runner.calls == 0
            await clock.advance_to(239.0)
            await asyncio.wait_for(telegram.sent.wait(), timeout=3.0)
            await constructed[0].reconcile_once()
        except TimeoutError as exc:
            state = (
                load_periodic_state(tmp_path).payload
                if (tmp_path / "reporting" / "periodic_state.json").exists()
                else None
            )
            task_error = task.exception() if task.done() else None
            raise AssertionError(
                f"H3 due slot did not deliver: constructed={len(constructed)}, "
                f"runner_calls={runner.calls}, task_error={task_error!r}, "
                f"artifact_failures={artifact_reader.failures!r}, state={state!r}"
            ) from exc
    finally:
        await supervisor.stop()
        await task

    assert len(constructed) == 1
    assert live.starts == 1
    assert live.stops == 1
    assert archive.calls >= 1
    assert runner.calls == 1
    assert artifact_reader.failures == []
    assert telegram.closed == 1
    assert telegram.deliveries == [(_immutable_png(), "immutable H3 cutover proof")]
    state = load_periodic_state(tmp_path).payload
    assert state["last_terminal"]["status"] == "SUCCEEDED"
    assert sys.modules.get("cryodaq.notifications.periodic_report") is legacy_before


@pytest.mark.parametrize(
    ("periodic_enabled", "experiment_mode"),
    [(False, True), (True, False)],
    ids=["disabled-live", "enabled-config-replay"],
)
async def test_disabled_or_replay_runs_optional_llm_but_never_h3_or_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    periodic_enabled: bool,
    experiment_mode: bool,
) -> None:
    import cryodaq.agents.assistant_bootstrap as bootstrap
    import cryodaq.paths
    from cryodaq.launcher import _assistant_runtime_decision

    (tmp_path / "agent.yaml").write_text(_agent(enabled=True), encoding="utf-8")
    (tmp_path / "notifications.yaml").write_text(_notifications(enabled=periodic_enabled), encoding="utf-8")
    monkeypatch.setattr(cryodaq.paths, "get_config_dir", lambda: tmp_path)
    required, periodic = _assistant_runtime_decision(experiment_mode=experiment_mode)
    assert required and not periodic
    monkeypatch.setenv("CRYODAQ_ASSISTANT_EXPERIMENT_MODE", "1" if experiment_mode else "0")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "0")
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    windows_handlers = _install_windows_signal_double(bootstrap, monkeypatch)
    h2_stopped: list[bool] = []
    llm_runs: list[bool] = []

    class H2:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            h2_stopped.append(True)

    async def llm(*, shutdown_event: asyncio.Event, **_kwargs: object) -> None:
        llm_runs.append(True)
        shutdown_event.set()

    monkeypatch.setattr(bootstrap, "ReportCoordinator", H2)
    monkeypatch.setattr(bootstrap, "_load_llm_runtime", lambda: llm)
    monkeypatch.setattr(
        bootstrap,
        "_load_periodic_runtime",
        lambda: pytest.fail("disabled/replay path constructed H3"),
    )
    try:
        await bootstrap.run(config_dir=tmp_path, data_dir=tmp_path)
    finally:
        assert windows_handlers[21] == bootstrap.signal.SIG_DFL
    assert llm_runs == [True]
    assert h2_stopped == [True]


async def test_h3_readiness_failure_has_no_legacy_fallback_or_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent.yaml").write_text(_agent(enabled=False), encoding="utf-8")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_EXPERIMENT_MODE", "1")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    destination: list[bytes] = []
    with pytest.raises(RuntimeError, match="h3 readiness failed"):
        await _run_bootstrap_h3(
            tmp_path,
            monkeypatch,
            destination=destination,
            fail_before_send=True,
        )
    assert destination == []


def test_inbound_notifications_and_llm_relay_contracts_remain_in_engine() -> None:
    source = ENGINE.read_text(encoding="utf-8")
    for required in (
        "TelegramCommandBot",
        "CompositionPhotoHandler",
        "EscalationService",
        'notif_raw.get("telegram", {})',
        'notif_raw.get("commands", {})',
        'tg_cfg.get("allowed_chat_ids")',
        'cmd_cfg.get("allowed_chat_ids")',
        'poll_interval_s=float(cmd_cfg.get("poll_interval_s", 2.0))',
        "verify_ssl=verify_ssl",
        'chat_id=tg_cfg.get("chat_id", 0)',
        "escalation_service = EscalationService(_esc_notifier, notif_raw)",
        "telegram_bot._query_agent = _RemoteAssistantQueryProxy()",
        '"alarm_cleared"',
        '"periodic_report_request"',
        'event_bus.unsubscribe("assistant_zmq_relay")',
        "await telegram_bot.start()",
        "await telegram_bot.stop()",
        "await _photo_handler.start()",
        "await _photo_handler.stop()",
        '_engine_config_path("notifications")',
    ):
        assert required in source

    bot_start = source.index("await telegram_bot.start()")
    photo_start = source.index("await _photo_handler.start()")
    relay_start = source.index('supervisor.spawn(\n        "assistant_event_relay"')
    scheduler_start = source.index("await scheduler.start()")
    assert bot_start < photo_start < relay_start < scheduler_start

    scheduler_stop = source.index("await scheduler.stop()")
    relay_stop = source.index('event_bus.unsubscribe("assistant_zmq_relay")')
    photo_stop = source.index("await _photo_handler.stop()")
    bot_stop = source.index("await telegram_bot.stop()")
    interlock_stop = source.index("await interlock_engine.stop()")
    assert scheduler_stop < relay_stop < photo_stop < bot_stop < interlock_stop
