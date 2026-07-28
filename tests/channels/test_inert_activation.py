from __future__ import annotations

import ast
from pathlib import Path


def test_only_approved_passive_adapters_import_channel_contract() -> None:
    source_root = Path(__file__).parents[2] / "src" / "cryodaq"
    channel_root = source_root / "channels"
    importers: set[str] = set()
    for path in source_root.rglob("*.py"):
        if path.is_relative_to(channel_root):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cryodaq.channels"):
                importers.add(path.relative_to(source_root).as_posix())
            elif isinstance(node, ast.Import) and any(
                alias.name.startswith("cryodaq.channels") for alias in node.names
            ):
                importers.add(path.relative_to(source_root).as_posix())
    assert importers == {
        "core/broker.py",
        "core/descriptor_transport.py",
        # Read-only descriptor classification keeps sensor diagnostics from
        # inferring physical quantity or role from channel names.
        "core/sensor_diagnostics.py",
        "core/zmq_bridge.py",
        "core/zmq_subprocess.py",
        # Reviewed F35 observational presentation only; authority remains
        # denied by test_descriptors.py and test_registry.py.
        "gui/shell/main_window_v2.py",
        "gui/shell/overlays/instruments_panel.py",
        "gui/shell/overlays/multiline_panel.py",
        "gui/state/descriptor_store.py",
        # gui/zmq_client.py removed 2026-07-25 (S1-zmq-transport slice):
        # its only prior use of cryodaq.channels was the ChannelDescriptorV1
        # return-type annotation on a local _descriptor_from_envelope()
        # helper. That helper no longer exists in that shape; descriptor
        # qualification now flows entirely through the already-approved
        # core/descriptor_transport.py (qualify_reading_descriptor ->
        # DescriptorQualifiedReading), which zmq_client.py still imports
        # and calls directly (zmq_client.py:44,1071). No direct dependency
        # on the channel-contract package remains in this file — confirmed
        # by re-grepping for both "cryodaq.channels" and the bare
        # "ChannelDescriptorV1" symbol name (zero hits either way).
        "storage/channel_descriptors.py",
        "storage/descriptor_archive.py",
        "storage/sqlite_writer.py",
    }


def test_channel_contract_has_no_product_subsystem_imports() -> None:
    source_root = Path(__file__).parents[2] / "src" / "cryodaq"
    forbidden = ("cryodaq.core", "cryodaq.drivers", "cryodaq.engine", "cryodaq.storage")
    offenders: list[tuple[str, str]] = []
    for path in (source_root / "channels").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(forbidden):
                offenders.append((path.name, node.module or ""))
            elif isinstance(node, ast.Import):
                offenders.extend((path.name, alias.name) for alias in node.names if alias.name.startswith(forbidden))
    assert offenders == []
