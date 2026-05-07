"""F31 H2 — VaultSink.write must offload sync I/O to a thread."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.sinks.base import ExperimentExport
from cryodaq.sinks.vault_sink import VaultSink


def _sample_export() -> ExperimentExport:
    return ExperimentExport(
        experiment_id="abc12345",
        title="Test",
        sample="S-001",
        operator="V",
        status="COMPLETED",
        started_at=datetime(2026, 5, 7, 10, 0, tzinfo=UTC),
        ended_at=datetime(2026, 5, 7, 14, 0, tzinfo=UTC),
        duration_h=4.0,
        template_id="custom",
    )


@pytest.mark.asyncio
async def test_vault_sink_write_runs_in_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VaultSink._write_file_sync must execute on a non-loop thread."""
    main_thread = threading.get_ident()
    captured: list[int] = []

    real_write = Path.write_text

    def _spy(self, content, *args, **kwargs):
        captured.append(threading.get_ident())
        return real_write(self, content, *args, **kwargs)

    monkeypatch.setattr("pathlib.Path.write_text", _spy)

    sink = VaultSink(tmp_path)
    result = await sink.write(_sample_export())

    assert result.success
    assert captured, "Path.write_text was not called"
    assert captured[0] != main_thread, (
        "VaultSink wrote on the asyncio loop thread"
    )
