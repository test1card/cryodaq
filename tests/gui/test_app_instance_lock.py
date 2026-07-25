"""GUI process lock ownership must keep one stable filesystem object."""

from __future__ import annotations

import ast
import inspect
import textwrap
from unittest.mock import MagicMock

from cryodaq.gui import app as gui_app


def test_gui_app_uses_exact_persistent_release_on_construction_failure_and_normal_exit() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(gui_app.main)))
    release_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "release_lock_exact"
    ]
    generic_release_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "release_lock"
    ]

    assert generic_release_calls == []
    assert len(release_calls) == 2
    for call in release_calls:
        assert len(call.args) == 2
        assert isinstance(call.args[0], ast.Name) and call.args[0].id == "lock_fd"
        assert isinstance(call.args[1], ast.Constant) and call.args[1].value == ".gui.lock"


def test_gui_app_imports_exact_release_without_generic_unlinking_release() -> None:
    module_tree = ast.parse(inspect.getsource(gui_app))
    imported: set[str] = set()
    for node in module_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "cryodaq.instance_lock":
            imported.update(alias.name for alias in node.names)

    assert "release_lock_exact" in imported
    assert "release_lock" not in imported


def test_gui_runtime_annunciation_terminal_retries_only_after_every_peer_settles() -> None:
    events: list[str] = []
    owners = gui_app._GuiRuntimeOwners()
    window = MagicMock()
    window.invalidate_descriptor_transport.side_effect = lambda: events.append("window_invalidated")
    window.settle_owned_workers.side_effect = lambda: events.append("window_workers") or True
    terminal_attempts = 0

    def complete_root_shutdown() -> None:
        nonlocal terminal_attempts
        terminal_attempts += 1
        events.append(f"annunciation_terminal_{terminal_attempts}")
        if terminal_attempts == 1:
            raise RuntimeError("audible HOLD remains owned")

    window.complete_root_shutdown.side_effect = complete_root_shutdown
    ingress = MagicMock()
    ingress.stop.side_effect = lambda: events.append("ingress")
    ingress.active = False
    bridge = MagicMock()
    bridge.shutdown.side_effect = lambda: events.append("bridge_shutdown")
    bridge.close.side_effect = lambda: events.append("bridge_terminal")
    owners.window = window
    owners.snapshot_ingress = ingress
    owners.bridge = bridge

    assert owners.settle() is False
    assert events == [
        "window_invalidated",
        "window_workers",
        "ingress",
        "bridge_shutdown",
        "bridge_terminal",
        "annunciation_terminal_1",
    ]
    assert "annunciation_terminal" not in owners._settled

    assert owners.settle() is True
    assert events[-1] == "annunciation_terminal_2"
    assert events.count("bridge_shutdown") == 1
    assert events.count("bridge_terminal") == 1
    assert "annunciation_terminal" in owners._settled


def test_gui_runtime_without_window_has_explicit_terminal_annunciation_owner() -> None:
    owners = gui_app._GuiRuntimeOwners()

    assert owners.settle() is True
    assert {"window", "annunciation_terminal"}.issubset(owners._settled)
