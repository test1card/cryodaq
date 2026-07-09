"""conftest for tests/replay_engine — golden-file regen flag (roadmap D4).

``--update-golden`` lets a developer intentionally refresh the checked-in
golden JSON after a deliberate analytics/alarm behavior change:

    pytest tests/replay_engine/test_golden_replay.py --update-golden
    pytest tests/replay_engine/test_golden_replay.py  # verify against the refreshed golden
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate golden JSON fixtures under tests/replay_engine/golden/ "
        "instead of asserting the harness output against them.",
    )


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-golden"))
