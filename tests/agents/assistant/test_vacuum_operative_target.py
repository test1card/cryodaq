"""The vacuum ETA must be reported against a target the stand can reach for.

The assistant used to ask for a hardcoded 1e-6 mbar. On this stand the gauge is
a Pirani specified only to 1e-4, and the engine's configured targets are
coarser still, so that question could only ever be answered "прогноз не
определён" — regardless of how the pump was doing.
"""

from cryodaq.agents.assistant.query.adapters.vacuum_adapter import _operative_target


def test_picks_the_coarsest_target_not_yet_reached():
    # 0.1 already reached (ETA 0.0); the next milestone is 0.05.
    target, eta = _operative_target({"1e-01": 0.0, "5e-02": 3600.0, "1e-02": 90000.0})
    assert target == 5e-2
    assert eta == 3600.0


def test_an_unreachable_next_target_is_still_the_answer():
    # Reporting "0.05 mbar: no forecast" is the truth. Silently skipping to a
    # finer target that happens to have a number would be worse.
    target, eta = _operative_target({"1e-01": 0.0, "5e-02": None, "1e-02": None})
    assert target == 5e-2
    assert eta is None


def test_all_targets_reached_returns_the_finest():
    target, eta = _operative_target({"1e-01": 0.0, "5e-02": 0.0, "1e-02": 0.0})
    assert target == 1e-2
    assert eta == 0.0


def test_no_targets_configured():
    assert _operative_target({}) == (None, None)


def test_unparseable_keys_are_ignored():
    target, eta = _operative_target({"not-a-number": 5.0, "1e-02": 120.0})
    assert target == 1e-2
    assert eta == 120.0


def test_ordering_does_not_depend_on_dict_order():
    ordered = _operative_target({"1e-01": 0.0, "5e-02": 10.0, "1e-02": 20.0})
    shuffled = _operative_target({"1e-02": 20.0, "1e-01": 0.0, "5e-02": 10.0})
    assert ordered == shuffled
