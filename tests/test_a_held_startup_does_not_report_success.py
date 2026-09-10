"""A launcher that never finished constructing must not exit 0.

`deploy/cryodaq.service` is Type=simple with Restart=on-failure. Under
Type=simple systemd considers the service started the moment the process is
forked, so a launcher sitting in a construction HOLD -- window shown, nothing
acquiring -- appears as active (running) for as long as it lives. When a person
eventually closes that window, Qt returns 0 and the run is recorded as a clean
success. Nothing retries, and the journal says the unit is fine.

That is the same shape as the modal-dialog defect that kept the unit disabled:
`_report_startup_refusal` exists because a process that blocks instead of
exiting never lets `Restart=on-failure` fire. This is one level up -- it does
not block on a dialog, it blocks on an event loop -- and it ends by claiming
success.

What is NOT changed here: the HOLD itself. It is entered only when
`_do_shutdown` did not settle, so acquired children may be in an unknown state
and exiting early could orphan them. Whether an unattended launcher should exit
at once is a decision with real risk and is left to the operator.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from cryodaq.launcher import _launcher_exit_code, main


def test_a_held_startup_reports_failure() -> None:
    assert _launcher_exit_code(construction_hold=True, qt_exit_code=0) == 1


def test_a_settled_startup_keeps_qt_s_verdict() -> None:
    assert _launcher_exit_code(construction_hold=False, qt_exit_code=0) == 0


@pytest.mark.parametrize("qt_exit_code", [1, 2, 130])
def test_a_failure_from_qt_is_never_overwritten(qt_exit_code: int) -> None:
    """Qt's own non-zero code says failure more precisely than this could."""
    assert _launcher_exit_code(construction_hold=True, qt_exit_code=qt_exit_code) == qt_exit_code
    assert _launcher_exit_code(construction_hold=False, qt_exit_code=qt_exit_code) == qt_exit_code


def test_the_launcher_actually_exits_through_this_rule() -> None:
    """A source guard, and it proves nothing about runtime behaviour.

    Standing up main() means a QApplication, an X display and the whole
    construction path. This catches the one change that would leave every test
    above green while the defect returned: main() calling sys.exit with Qt's
    code directly.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(main)))
    body = tree.body[0].body  # type: ignore[attr-defined]

    # The LAST statement, not "some exit somewhere". Requiring only that a
    # matching call appears anywhere let a reviewer reinstate the defect with
    # `sys.exit(exit_code) if construction_hold else sys.exit(_launcher_exit_code(...))`
    # -- the rule still present, and never reached on the path that needs it.
    final = body[-1]
    assert isinstance(final, ast.Expr), "main() no longer ends in a call"
    exit_call = final.value
    assert (
        isinstance(exit_call, ast.Call)
        and isinstance(exit_call.func, ast.Attribute)
        and exit_call.func.attr == "exit"
        and isinstance(exit_call.func.value, ast.Name)
        and exit_call.func.value.id == "sys"
    ), "main() no longer ends with sys.exit"

    through_the_rule = [
        exit_call
        for _ in (0,)
        if exit_call.args
        and isinstance(exit_call.args[0], ast.Call)
        and isinstance(exit_call.args[0].func, ast.Name)
        and exit_call.args[0].func.id == "_launcher_exit_code"
    ]

    assert through_the_rule, "the final exit does not consult the construction-hold rule"
    for call in through_the_rule:
        passed = {keyword.arg: keyword.value for keyword in call.args[0].keywords}
        # `stop_completed` joined the rule when a stop requested during startup
        # stopped being a construction failure: a stop that settles late still
        # HOLDs, and reporting failure for it would have `Restart=on-failure`
        # bring back a launcher the operator stopped. Required here rather than
        # merely tolerated -- dropping it silently restores that restart.
        assert set(passed) == {"construction_hold", "qt_exit_code", "stop_completed"}, (
            "the rule must be given the hold state, Qt's own code and whether a startup stop finished"
        )
        # Names, not just argument names: passing `construction_hold=False`
        # satisfies a check on the keywords alone and restores the defect in
        # full, which is exactly how this guard first failed.
        expected_names = {
            "construction_hold": "construction_hold",
            "qt_exit_code": "exit_code",
            "stop_completed": "stop_completed",
        }
        for name, node in passed.items():
            expected = expected_names[name]
            assert isinstance(node, ast.Name) and node.id == expected, (
                f"{name} must be the run's own {expected}, not a literal"
            )
