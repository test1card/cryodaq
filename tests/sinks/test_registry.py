"""F31 — SinkRegistry tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from cryodaq.sinks.base import ExperimentExport, Sink, SinkResult
from cryodaq.sinks.registry import SinkRegistry
from cryodaq.sinks.vault_sink import VaultSink
from cryodaq.sinks.webhook_sink import WebhookSink


def _write_cfg(tmp_path: Path, payload: dict) -> Path:
    cfg = tmp_path / "sinks.yaml"
    cfg.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return cfg


def test_registry_loads_vault_from_config(tmp_path):
    cfg = _write_cfg(
        tmp_path,
        {"sinks": {"vault": {"enabled": True, "directory": str(tmp_path / "vault")}}},
    )
    reg = SinkRegistry()
    reg.load_config(cfg)
    assert len(reg.sinks) == 1
    assert isinstance(reg.sinks[0], VaultSink)


def test_registry_skips_disabled_vault(tmp_path):
    cfg = _write_cfg(tmp_path, {"sinks": {"vault": {"enabled": False}}})
    reg = SinkRegistry()
    reg.load_config(cfg)
    assert reg.sinks == []


def test_registry_no_config_no_sinks(tmp_path):
    reg = SinkRegistry()
    reg.load_config(tmp_path / "nonexistent.yaml")
    assert reg.sinks == []


def test_registry_loads_webhook_with_headers(tmp_path):
    cfg = _write_cfg(
        tmp_path,
        {
            "sinks": {
                "webhooks": [
                    {
                        "enabled": True,
                        "url": "http://example.com/in",
                        "extra_headers": {"Authorization": "Bearer x"},
                    }
                ]
            }
        },
    )
    reg = SinkRegistry()
    reg.load_config(cfg)
    assert len(reg.sinks) == 1
    sink = reg.sinks[0]
    assert isinstance(sink, WebhookSink)
    assert sink.url == "http://example.com/in"


def test_registry_skips_webhook_without_url(tmp_path):
    cfg = _write_cfg(tmp_path, {"sinks": {"webhooks": [{"enabled": True}]}})
    reg = SinkRegistry()
    reg.load_config(cfg)
    assert reg.sinks == []


class _RecordingSink(Sink):
    name = "recording"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[ExperimentExport] = []
        self._fail = fail

    async def write(self, export: ExperimentExport) -> SinkResult:
        self.calls.append(export)
        if self._fail:
            return SinkResult(self.name, success=False, target="x", error="boom")
        return SinkResult(self.name, success=True, target="x")


def _sample_export() -> ExperimentExport:
    return ExperimentExport(
        experiment_id="abc",
        title="t",
        sample="s",
        operator="o",
        status="COMPLETED",
        started_at=datetime.now(UTC),
        ended_at=None,
        duration_h=None,
    )


@pytest.mark.asyncio
async def test_registry_dispatch_fans_out_to_all_sinks():
    reg = SinkRegistry()
    s1 = _RecordingSink()
    s2 = _RecordingSink()
    reg._sinks.extend([s1, s2])
    results = await reg.dispatch(_sample_export())
    assert len(results) == 2
    assert all(r.success for r in results)
    assert len(s1.calls) == 1
    assert len(s2.calls) == 1


@pytest.mark.asyncio
async def test_registry_dispatch_records_failures_in_log():
    reg = SinkRegistry()
    reg._sinks.append(_RecordingSink(fail=True))
    await reg.dispatch(_sample_export())
    assert len(reg.recent_results) == 1
    assert reg.recent_results[0].success is False


@pytest.mark.asyncio
async def test_registry_dispatch_with_no_sinks_returns_empty():
    reg = SinkRegistry()
    results = await reg.dispatch(_sample_export())
    assert results == []


class _RaisingSink(Sink):
    name = "raises"

    async def write(self, export: ExperimentExport) -> SinkResult:  # noqa: ARG002
        raise RuntimeError("buggy sink raised")


@pytest.mark.asyncio
async def test_registry_dispatch_converts_raising_sink_to_failure():
    """A misbehaving Sink that raises must not propagate out of dispatch()."""
    reg = SinkRegistry()
    reg._sinks.extend([_RaisingSink(), _RecordingSink()])
    results = await reg.dispatch(_sample_export())
    assert len(results) == 2
    assert results[0].sink_name == "raises"
    assert results[0].success is False
    assert "buggy sink raised" in (results[0].error or "")
    assert results[1].success is True
    # Failure must also land in audit buffer.
    assert any(not r.success for r in reg.recent_results)
