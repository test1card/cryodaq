"""The fork-server topology, tested against the command lines the platform really produces.

WHY THIS MODULE EXISTS. Python 3.14 makes `forkserver` the Linux default and the
laboratory target is 3.14.6, so the bridge is no longer a direct child of the launcher.
The check that accepts it was relaxed to a two-step chain, and a relaxation of an identity
check is exactly the thing that must not rest on one person's manual run.

THE MEASUREMENT THESE TESTS ENCODE. On the laboratory interpreter, a process forked BY the
fork server inherits the fork server's command line EXACTLY. Both print:

    python -B -c "import sys; from multiprocessing.forkserver import main; main(...)" ...

So the module token identifies the fork server AND every child it makes -- the bridge
included. Only the parent separates them: the fork server and the resource tracker are
direct children of the launcher, their children are not. Every case below is built from
that measured shape rather than from an invented one, because a topology invented to suit
the check tests the invention.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "soak_mock_stack.py"
_SPEC = importlib.util.spec_from_file_location("soak_mock_stack_forkserver", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
soak = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = soak
_SPEC.loader.exec_module(soak)

# The measured argv, shortened only where the content carries no meaning for the check.
_FORKSERVER_ARGV = (
    "python",
    "-B",
    "-c",
    "import sys; from multiprocessing.forkserver import main; main(3, 5, ['__main__'], "
    "sys_argv=sys.argv[1:], **{'sys_path': [...], 'main_path': '...', 'authkey_r': 7})",
    "/path/to/launcher.py",
)
_TRACKER_ARGV = (
    "python",
    "-B",
    "-c",
    "from multiprocessing.resource_tracker import main;main(3)",
)

_ENGINE_ARGV = ("python", "-m", "cryodaq.engine", "--mock")
_ASSISTANT_ARGV = ("python", "-m", "cryodaq.agents.assistant_bootstrap")

LAUNCHER_PID = 793
FORKSERVER_PID = 820
TRACKER_PID = 801
BRIDGE_PID = 821
ENGINE_PID = 795
ASSISTANT_PID = 797


def _snapshot(pid: int, started: int, parent: int | None, argv: tuple[str, ...]) -> soak.ProcessSnapshot:
    return soak.ProcessSnapshot(
        soak.ProcessIdentity(pid, started),
        parent,
        argv,
        "python",
        100,
        1,
        2,
        True,
    )


def _rows(*extra: soak.ProcessSnapshot) -> list[soak.ProcessSnapshot]:
    """The laboratory's measured tree: launcher, tracker, fork server, bridge."""

    return [
        *_base(),
        # The bridge is forked BY the fork server and therefore carries the fork server's
        # command line, byte for byte. This is the measured fact the check has to survive.
        _snapshot(BRIDGE_PID, 130, FORKSERVER_PID, _FORKSERVER_ARGV),
        *extra,
    ]


def _base() -> list[soak.ProcessSnapshot]:
    """Launcher, both multiprocessing helpers, and the two roles the classifier demands.

    The engine and the assistant are here because `classify_tree` refuses a tree that is
    missing a required role. Leaving them out made three refusal tests pass for the WRONG
    reason -- they raised `missing required process roles` and never reached the check
    under test. A refusal that fires for a reason the test did not intend proves nothing.
    """

    return [
        _snapshot(LAUNCHER_PID, 100, 1, ("launcher",)),
        _snapshot(TRACKER_PID, 110, LAUNCHER_PID, _TRACKER_ARGV),
        _snapshot(FORKSERVER_PID, 120, LAUNCHER_PID, _FORKSERVER_ARGV),
        _snapshot(ENGINE_PID, 140, LAUNCHER_PID, _ENGINE_ARGV),
        _snapshot(ASSISTANT_PID, 150, LAUNCHER_PID, _ASSISTANT_ARGV),
    ]


def _classify(rows, *, bridge_pid: int = BRIDGE_PID, bridge_started: int = 130):
    root = soak.ProcessIdentity(LAUNCHER_PID, 100)
    tree = soak.descendants(rows, root)
    return soak.classify_tree(tree, root, bridge_identity=soak.ProcessIdentity(bridge_pid, bridge_started))


def test_the_measured_laboratory_tree_classifies() -> None:
    """The whole point of the relaxation: this topology must be accepted."""

    result = _classify(_rows())
    assert result["bridge"] == soak.ProcessIdentity(BRIDGE_PID, 130)
    assert result["launcher"] == soak.ProcessIdentity(LAUNCHER_PID, 100)


def test_both_multiprocessing_helpers_are_accounted_for_by_name() -> None:
    """Accepting only the fork server left the resource tracker unclassified on the machine."""

    result = _classify(_rows())
    accounted = {identity.pid for identity in result.values()}
    assert TRACKER_PID not in accounted, "the tracker must be infrastructure, not a role"
    assert FORKSERVER_PID not in accounted, "the fork server must be infrastructure, not a role"


def test_an_unexpected_child_of_the_fork_server_is_REFUSED_despite_the_inherited_argv() -> None:
    """This is the case the inherited command line hides, and the reason for the parent test.

    A second process forked by the fork server carries the same `multiprocessing.forkserver`
    token as the fork server itself. Matching on the token alone would excuse it by name and
    the guard's stated property -- every live descendant is accounted for -- would be false
    for exactly the descendants it exists to catch.
    """

    stranger = _snapshot(900, 140, FORKSERVER_PID, _FORKSERVER_ARGV)
    with pytest.raises(ValueError, match="unclassified descendant"):
        _classify(_rows(stranger))


def test_a_grandchild_of_the_fork_server_cannot_pose_as_the_fork_server() -> None:
    """The bridge's parent must be the launcher or a fork server that is a DIRECT child.

    Here the bridge's parent is a process that carries the fork-server token but hangs off
    the fork server rather than off the launcher. Without the direct-child requirement that
    process joins the accepted set and this bridge is admitted.
    """

    impostor = _snapshot(950, 160, FORKSERVER_PID, _FORKSERVER_ARGV)
    rows = [*_base(), impostor, _snapshot(BRIDGE_PID, 130, 950, _FORKSERVER_ARGV)]
    # It must refuse because the bridge's parent is not a fork server this launcher owns,
    # not because the tree is short of a role.
    with pytest.raises(ValueError, match="neither a launcher child nor a fork-server child"):
        _classify(rows)


def test_a_bridge_that_is_a_direct_child_still_classifies() -> None:
    """The pre-3.14 topology must not stop working because the newer one now does."""

    rows = [
        _snapshot(LAUNCHER_PID, 100, 1, ("launcher",)),
        _snapshot(ENGINE_PID, 140, LAUNCHER_PID, _ENGINE_ARGV),
        _snapshot(ASSISTANT_PID, 150, LAUNCHER_PID, _ASSISTANT_ARGV),
        _snapshot(BRIDGE_PID, 130, LAUNCHER_PID, ("inherited-launcher-argv",)),
    ]
    assert _classify(rows)["bridge"] == soak.ProcessIdentity(BRIDGE_PID, 130)


def test_a_bridge_parented_outside_the_launcher_is_refused() -> None:
    """Neither a launcher child nor a fork-server child: the check must still say no."""

    rows = [*_base(), _snapshot(BRIDGE_PID, 130, 4242, _FORKSERVER_ARGV)]
    with pytest.raises(ValueError, match="positive bridge identity is absent"):
        _classify(rows)
