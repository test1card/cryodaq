"""The conductance panel starts the source itself.

The sweep's first command used to be ``keithley_set_target``, which the
SafetyManager refuses for a channel that is not running:

    Авто-команда Keithley не подтверждена: Channel smub not active

So a sweep begun from an idle source died on its first command. The operator
had to open the Keithley tab, start the channel by hand, and come back --
splitting one action across two tabs, which is how someone ends up energizing a
source they did not mean to. The operator's words: "you cant stplit control on
2 tabs".

Three paths are pinned here:

* an idle source is STARTED, at the first power, under the panel's own
  compliance limits;
* a source the operator already started by hand is not a failure -- the sweep
  sets the first power instead of latching;
* every other refusal still stops the sweep.
"""

import pytest

from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel


class _Recorder:
    """Captures dispatched commands and replies with a scripted result."""

    def __init__(self, replies):
        self.sent: list[dict] = []
        self._replies = list(replies)
        self.latched: list[str] = []
        self.armed = 0

    def send(self, command, *, evidence_power_channel=None, evidence_temperature_channels=None):
        self.sent.append(command)
        return True


@pytest.fixture
def panel(monkeypatch):
    """A panel object without Qt construction: only the dispatch logic is under test."""
    obj = ConductivityPanel.__new__(ConductivityPanel)
    return obj


# ---------------------------------------------------------------------------
# The first step starts the source
# ---------------------------------------------------------------------------


def test_first_step_issues_keithley_start_not_set_target(panel, monkeypatch):
    sent: list[dict] = []
    panel._auto_power_list = [0.25, 0.5]
    panel._auto_bound_power_channel = "P"
    panel._auto_bound_temperature_channels = ("Т1", "Т2", "Т13", "Т14")
    panel._auto_power_target_dispatched = False

    class _Spin:
        def __init__(self, v): self._v = v
        def value(self): return self._v

    panel._v_comp_spin = _Spin(40.0)
    panel._i_comp_spin = _Spin(1.0)
    monkeypatch.setattr(ConductivityPanel, "_smu_channel_for", lambda self, ch: "smub")
    monkeypatch.setattr(
        ConductivityPanel,
        "_send_auto_cmd",
        lambda self, cmd, **kw: (sent.append(cmd), True)[1],
    )
    monkeypatch.setattr(ConductivityPanel, "_latch_auto_outcome_unknown", lambda self, r: sent.append({"latch": r}))

    class _Timer:
        def start(self): pass

    panel._auto_timer = _Timer()
    emitted = []

    class _Sig:
        def emit(self): emitted.append(True)

    panel.auto_sweep_started = _Sig()

    panel._dispatch_first_auto_target()

    assert len(sent) == 1, sent
    command = sent[0]
    assert command["cmd"] == "keithley_start", "an idle source must be STARTED, not targeted"
    assert command["channel"] == "smub"
    assert command["p_target"] == 0.25, "the sweep starts at its first power"
    assert command["v_comp"] == 40.0, "the panel states the limits it starts under"
    assert command["i_comp"] == 1.0
    assert emitted == [True]


# ---------------------------------------------------------------------------
# A hand-started channel is not a failure
# ---------------------------------------------------------------------------


def _result_panel(monkeypatch, sent, latched, armed=None):
    """A panel positioned to accept one authoritative reply."""
    obj = ConductivityPanel.__new__(ConductivityPanel)
    monkeypatch.setattr(
        ConductivityPanel,
        "_send_auto_cmd",
        lambda self, cmd, **kw: (sent.append(cmd), True)[1],
    )
    monkeypatch.setattr(
        ConductivityPanel, "_latch_auto_outcome_unknown", lambda self, reason: latched.append(reason)
    )
    monkeypatch.setattr(
        ConductivityPanel,
        "_arm_auto_step_evidence",
        lambda self, **kw: (armed.append(kw) if armed is not None else None),
    )
    monkeypatch.setattr(ConductivityPanel, "_update_control_enablement", lambda self: None)
    obj._auto_settled_command_tokens = set()
    obj._auto_workers = []
    obj._auto_pending_token = 7
    obj._auto_operation_generation = 3
    obj._auto_connection_generation = 5
    obj._connected = True
    obj._auto_binding_resolution = "durable"
    obj._auto_pending_stop_intent = None
    return obj


def _reply(panel, command, result, **kw):
    panel._on_auto_cmd_result(
        7,
        command,
        result,
        5,
        3,
        evidence_power_channel="P",
        evidence_temperature_channels=("\u04221", "\u04222"),
        **kw,
    )


START = {"cmd": "keithley_start", "channel": "smub", "p_target": 0.25, "v_comp": 40.0, "i_comp": 1.0}


def test_already_active_sets_the_target_instead_of_latching(monkeypatch):
    sent: list[dict] = []
    latched: list[str] = []
    panel = _result_panel(monkeypatch, sent, latched)

    _reply(panel, START, {"ok": False, "error": "Channel smub already active"})

    assert latched == [], f"a hand-started channel must not latch the sweep: {latched}"
    assert len(sent) == 1, sent
    assert sent[0]["cmd"] == "keithley_set_target"
    assert sent[0]["p_target"] == 0.25, "the first power is still the first power"
    assert sent[0]["channel"] == "smub"


def test_any_other_refusal_still_stops_the_sweep(monkeypatch):
    sent: list[dict] = []
    latched: list[str] = []
    panel = _result_panel(monkeypatch, sent, latched)

    _reply(panel, START, {"ok": False, "error": "Start not allowed from fault_latched"})

    assert sent == [], "only 'already active' is recovered"
    assert len(latched) == 1
    assert "fault_latched" in latched[0]


def test_a_started_source_arms_the_step_evidence(monkeypatch):
    """A start opens an evidence epoch exactly as a target does."""
    sent: list[dict] = []
    latched: list[str] = []
    armed: list[dict] = []
    panel = _result_panel(monkeypatch, sent, latched, armed)

    _reply(panel, START, {"ok": True})

    assert latched == []
    assert armed == [{"power_channel": "P", "temperature_channels": ("\u04221", "\u04222")}]


def test_a_set_target_reply_still_arms_evidence(monkeypatch):
    """The pre-existing path is unchanged."""
    sent: list[dict] = []
    latched: list[str] = []
    armed: list[dict] = []
    panel = _result_panel(monkeypatch, sent, latched, armed)

    _reply(panel, {"cmd": "keithley_set_target", "channel": "smub", "p_target": 0.5}, {"ok": True})

    assert latched == []
    assert len(armed) == 1
