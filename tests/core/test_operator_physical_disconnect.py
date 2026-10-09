"""Teardown may proceed on a physical fact the software cannot observe.

When the reviewed source is unplugged from mains it can never report OFF, so
`launcher_shutdown` holds forever on `launcher_shutdown_global_off_unverified`
and the launcher stays in HOLD. On 2026-09-01 that turned a restart into an
eighteen-minute outage.

The operator may state the fact instead. It is carried as one boolean on the
SAME capability-bound shutdown request that is already being authorised -- no
command, no retained state, no evidence tier, no receipt field, no schema
change, nothing to clear afterwards -- and it authorises THIS teardown and
nothing else.

The receipt is deliberately unchanged. A SUCCESS receipt carrying unverified
evidence can only mean the engine accepted the assertion, because its gate
refuses otherwise; the receipt is already bound to engine instance and request
id; and the engine's CRITICAL log records the human reason. Echoing the flag
back would prove nothing the launcher does not already know.

Removing the instrument from configuration does not help and was measured:
with no reviewed source, emergency_off returns ok=True with active_channels=[]
but off_tier=command_only and verified_off=False, so the gate still refuses.
"""

import asyncio
from pathlib import Path

import pytest

from cryodaq.drivers.contracts import parse_global_off_evidence
from cryodaq.engine import _shutdown_command_identity

INSTANCE = "a" * 32
REQUEST = "b" * 32
CAPABILITY = "c" * 64


def _envelope(**extra):
    return {
        "cmd": "launcher_shutdown",
        "engine_instance_id": INSTANCE,
        "request_id": REQUEST,
        "shutdown_capability": CAPABILITY,
        **extra,
    }


# ---------------------------------------------------------------------------
# The assertion rides the existing capability-bound envelope
# ---------------------------------------------------------------------------


def test_the_plain_shutdown_envelope_is_still_accepted():
    assert _shutdown_command_identity(_envelope()) == (INSTANCE, REQUEST, CAPABILITY)


def test_the_envelope_may_carry_the_one_shot_assertion():
    identity = _shutdown_command_identity(_envelope(operator_physical_disconnect=True))
    assert identity == (INSTANCE, REQUEST, CAPABILITY), (
        "the assertion must ride the request that is already capability-bound"
    )


def test_the_assertion_must_be_exactly_true():
    """No truthy strings, no 1, no None: an explicit human statement only."""
    for value in ("true", 1, "yes", None, False, [], {}):
        assert _shutdown_command_identity(_envelope(operator_physical_disconnect=value)) is None, value


def test_an_unknown_key_still_fails_closed():
    assert _shutdown_command_identity(_envelope(something_else=True)) is None
    assert _shutdown_command_identity(_envelope(operator_physical_disconnect=True, extra=1)) is None


def test_a_missing_required_key_still_fails_closed():
    envelope = _envelope(operator_physical_disconnect=True)
    del envelope["shutdown_capability"]
    assert _shutdown_command_identity(envelope) is None


# ---------------------------------------------------------------------------
# It authorises teardown, and nothing else
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_assertion_never_becomes_device_evidence():
    """SourceOffEvidence is untouched; verified_off stays False."""
    from cryodaq.core.safety_broker import SafetyBroker
    from cryodaq.core.safety_manager import SafetyManager

    manager = SafetyManager(SafetyBroker(), keithley_driver=None, mock=False)
    result = await manager.emergency_off(channel=None)
    evidence = parse_global_off_evidence(result.get("off_evidence"))

    assert evidence is not None
    assert evidence.verified_off is False, (
        "an operator statement must never be reported as device-verified OFF"
    )
    assert str(evidence.off_tier) == "command_only", "no new evidence tier was introduced"


@pytest.mark.asyncio
async def test_nothing_is_retained_after_the_assertion():
    """No state to clear on restart, reconnection or configuration change."""
    from cryodaq.core.safety_broker import SafetyBroker
    from cryodaq.core.safety_manager import SafetyManager

    manager = SafetyManager(SafetyBroker(), keithley_driver=None, mock=False)
    before = await manager.emergency_off(channel=None)
    # The assertion lives only in one shutdown request; the manager never sees it.
    after = await manager.emergency_off(channel=None)
    assert before.get("off_evidence") == after.get("off_evidence")
    assert not any(
        "physical_disconnect" in name for name in vars(manager)
    ), "the assertion must not be retained anywhere in SafetyManager"


def test_the_safety_manager_gained_no_assertion_entry_point():
    from cryodaq.core.safety_manager import SafetyManager

    assert not [name for name in dir(SafetyManager) if "physical_disconnect" in name], (
        "no new command or method: the assertion rides the existing shutdown request"
    )


def test_energising_policy_is_unchanged():
    """require_keithley_for_run must survive untouched."""
    from pathlib import Path

    safety_yaml = Path(__file__).resolve().parents[2] / "config" / "safety.yaml"
    assert "require_keithley_for_run: true" in safety_yaml.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The launcher gate accepts exactly these two authorisations
# ---------------------------------------------------------------------------


def _receipt(*, verified_off: bool) -> dict:
    """The ORDINARY receipt shape. Unchanged by this work."""
    from cryodaq.drivers.contracts import SourceOffEvidence, SourceOffResult, SourceOffTier

    evidence = (
        SourceOffEvidence.from_global_result(SourceOffTier.VERIFIED_OFF, SourceOffResult.DEVICE_REPORTED_OFF)
        if verified_off
        else SourceOffEvidence.from_global_result(SourceOffTier.COMMAND_ONLY, SourceOffResult.COMMAND_ACCEPTED)
    )
    return {"off_evidence": evidence.receipt_payload()}


def _launcher_would_tear_down(receipt: dict, *, launcher_asserted: bool) -> bool:
    """The launcher's gate: device evidence, or its own asserted request."""
    evidence = parse_global_off_evidence(receipt["off_evidence"])
    return evidence is not None and (evidence.verified_off or launcher_asserted is True)


def test_verified_off_authorises_teardown():
    assert _launcher_would_tear_down(_receipt(verified_off=True), launcher_asserted=False) is True


def test_the_assertion_authorises_teardown_without_claiming_verified_off():
    receipt = _receipt(verified_off=False)
    assert _launcher_would_tear_down(receipt, launcher_asserted=True) is True
    assert parse_global_off_evidence(receipt["off_evidence"]).verified_off is False


def test_neither_authorisation_holds_the_launcher():
    assert _launcher_would_tear_down(_receipt(verified_off=False), launcher_asserted=False) is False


def test_the_ordinary_receipt_shape_is_unchanged():
    """No new mandatory field, so no schema bump and no ordinary-receipt churn.

    An ordinary shutdown must produce exactly the receipt it always did. The
    assertion changes what the launcher ACCEPTS, not what the engine reports.
    """
    from pathlib import Path

    from cryodaq import engine, launcher

    assert engine._ENGINE_SHUTDOWN_RECEIPT_SCHEMA == "cryodaq.engine_shutdown.v2"
    assert launcher._ENGINE_SHUTDOWN_RECEIPT_SCHEMA == "cryodaq.engine_shutdown.v2"

    source = (Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "launcher.py").read_text(encoding="utf-8")
    keys_block = source.split("expected_receipt_keys = {", 1)[1].split("}", 1)[0]
    assert "operator_physical_disconnect" not in keys_block, (
        "the assertion must not become a mandatory receipt field"
    )


def test_the_launcher_flag_dies_with_the_request_identity():
    """It can never outlive the request that carried it.

    Reset at every site that clears `_engine_shutdown_request_id`, and nowhere
    else, so a later teardown cannot inherit an earlier operator's statement.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "launcher.py").read_text(encoding="utf-8")
    request_resets = source.count("self._engine_shutdown_request_id = None")
    flag_resets = source.count("self._engine_shutdown_operator_asserted = False")
    assert request_resets > 0
    assert flag_resets == request_resets, (
        f"{flag_resets} flag resets for {request_resets} request-identity resets"
    )


# ---------------------------------------------------------------------------
# The confirmation is explicit, one-shot, and never comes from configuration
# ---------------------------------------------------------------------------


class _Recorder:
    """Just enough LauncherWindow to exercise the confirmation slot."""

    def __init__(self) -> None:
        self._source_disconnect_confirmation = None


def test_a_confirmation_must_name_its_source():
    from cryodaq.launcher import LauncherWindow

    recorder = _Recorder()
    for bad in ("", "   ", None, 7):
        with pytest.raises(ValueError, match="name its source"):
            LauncherWindow.confirm_source_physically_disconnected(recorder, bad)
    assert recorder._source_disconnect_confirmation is None


def test_a_confirmation_is_recorded_against_the_named_source():
    from cryodaq.launcher import LauncherWindow

    recorder = _Recorder()
    LauncherWindow.confirm_source_physically_disconnected(recorder, " Keithley_1 ")
    assert recorder._source_disconnect_confirmation == "Keithley_1"


def test_configuration_can_never_raise_the_confirmation():
    """A persistent flag would survive reconnection and release a shutdown on a
    source that is CONNECTED but whose OFF cannot be verified because
    communication failed. Only an explicit act may raise it.
    """
    import cryodaq.launcher as launcher_module

    assert not hasattr(launcher_module, "_reviewed_source_declared_physically_disconnected")
    source = Path(launcher_module.__file__).read_text(encoding="utf-8")
    raising = [
        line
        for line in source.splitlines()
        if "_source_disconnect_confirmation =" in line and "None" not in line
    ]
    assert len(raising) == 1, f"the confirmation is raised in {len(raising)} places: {raising}"
    assert "confirm_source_physically_disconnected" in source


def test_the_instruments_schema_carries_no_disconnect_declaration():
    """Removed with the automatic path, so no profile can imply the authority."""
    from cryodaq.drivers import registry

    assert "physically_disconnected" not in Path(registry.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Teardown is released, and nothing else is
# ---------------------------------------------------------------------------


def _teardown_released(*, verified_off: bool, declared: bool) -> bool:
    """Drive the real release gate, not a copy of its condition."""
    from types import SimpleNamespace

    from cryodaq.drivers.contracts import SourceOffEvidence, SourceOffResult, SourceOffTier
    from cryodaq.engine import PROTOCOL_VERSION, _request_teardown_after_shutdown_receipt

    evidence = (
        SourceOffEvidence.from_global_result(SourceOffTier.VERIFIED_OFF, SourceOffResult.DEVICE_REPORTED_OFF)
        if verified_off
        else SourceOffEvidence.from_global_result(SourceOffTier.COMMAND_ONLY, SourceOffResult.COMMAND_ACCEPTED)
    )
    receipt = {
        "ok": True,
        "engine_instance_id": INSTANCE,
        "request_id": REQUEST,
        "off_evidence": evidence.receipt_payload(),
        "teardown_requested": True,
    }
    released: list[bool] = []
    context = SimpleNamespace(
        shutdown_receipt=receipt,
        engine_instance_id=INSTANCE,
        shutdown_event=SimpleNamespace(set=lambda: released.append(True)),
    )
    cmd = _envelope(**({"operator_physical_disconnect": True} if declared else {}))
    _request_teardown_after_shutdown_receipt(context, cmd, {**receipt, "proto": PROTOCOL_VERSION})
    return bool(released)


def test_verified_off_releases_teardown():
    assert _teardown_released(verified_off=True, declared=False) is True


def test_the_declaration_releases_teardown_without_device_evidence():
    """The gap that made the committed assertion inert."""
    assert _teardown_released(verified_off=False, declared=True) is True


def test_neither_leaves_the_engine_running():
    assert _teardown_released(verified_off=False, declared=False) is False


# ---------------------------------------------------------------------------
# The GUI action: explicit, scoped, one-shot, dropped on cancel
# ---------------------------------------------------------------------------


class _Tray(_Recorder):
    def __init__(self, source: str | None) -> None:
        super().__init__()
        self._source = source

    def _configured_reviewed_source_name(self):
        return self._source

    def confirm_source_physically_disconnected(self, source_name: str) -> None:
        from cryodaq.launcher import LauncherWindow

        LauncherWindow.confirm_source_physically_disconnected(self, source_name)


def _confirm_handler():
    from cryodaq.launcher import LauncherWindow

    return LauncherWindow._on_confirm_source_disconnected


def _patch_dialog(monkeypatch, answer):
    from PySide6.QtWidgets import QMessageBox

    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: answer))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[1])))
    return warned


def test_confirming_arms_exactly_one_attempt(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox

    _patch_dialog(monkeypatch, QMessageBox.StandardButton.Yes)
    tray = _Tray("Keithley_1")
    _confirm_handler()(tray)
    assert tray._source_disconnect_confirmation == "Keithley_1"


def test_declining_arms_nothing_and_drops_anything_already_armed(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox

    _patch_dialog(monkeypatch, QMessageBox.StandardButton.No)
    tray = _Tray("Keithley_1")
    tray._source_disconnect_confirmation = "Keithley_1"
    _confirm_handler()(tray)
    assert tray._source_disconnect_confirmation is None, "a cancelled dialog left an armed confirmation"


def test_no_configured_source_means_nothing_to_confirm(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox

    warned = _patch_dialog(monkeypatch, QMessageBox.StandardButton.Yes)
    tray = _Tray(None)
    _confirm_handler()(tray)
    assert tray._source_disconnect_confirmation is None
    assert warned, "the operator was not told there is nothing to confirm"


def test_the_ordinary_quit_path_is_fail_closed_without_a_confirmation():
    """No confirmation, no assertion on the wire — the shutdown stays held."""
    import inspect

    from cryodaq.launcher import LauncherWindow

    source = inspect.getsource(LauncherWindow)
    raising = [
        line.strip()
        for line in source.splitlines()
        if '"operator_physical_disconnect"' in line and "shutdown_command[" in line
    ]
    assert len(raising) == 1, raising
    # It is reachable only behind the armed one-shot, and the slot is cleared
    # in the same block.
    block = source.split("confirmed_source = getattr")[1].split("worker = _EngineShutdownWorker")[0]
    assert 'shutdown_command["operator_physical_disconnect"] = True' in block
    assert "self._source_disconnect_confirmation = None" in block, "the confirmation is not consumed"


# ---------------------------------------------------------------------------
# Contrary evidence invalidates an armed confirmation
# ---------------------------------------------------------------------------


class _Armed(_Recorder):
    def __init__(self, active_channels) -> None:
        super().__init__()
        self._source_disconnect_confirmation = "Keithley_1"
        self._last_safety_state = type("S", (), {"active_channels": active_channels})()


def _invalidate():
    from cryodaq.launcher import LauncherWindow

    return LauncherWindow._invalidate_disconnect_confirmation_on_contrary_evidence


def test_an_energised_source_discards_the_confirmation():
    """The statement is "the source is unplugged". An energised output disproves it.

    Without this the confirmation had no bound inside one engine incarnation:
    armed truthfully today, the source re-plugged and run next week, then a
    communication failure at the eventual shutdown would let a week-old
    statement release teardown on an energised source.
    """
    window = _Armed(["smua"])
    _invalidate()(window)
    assert window._source_disconnect_confirmation is None


def test_an_idle_source_leaves_the_confirmation_armed():
    window = _Armed([])
    _invalidate()(window)
    assert window._source_disconnect_confirmation == "Keithley_1"


def test_unknown_safety_state_does_not_discard():
    """Absence of evidence is not contrary evidence."""
    window = _Armed([])
    window._last_safety_state = None
    _invalidate()(window)
    assert window._source_disconnect_confirmation == "Keithley_1"


def test_invalidation_is_a_no_op_when_nothing_is_armed():
    window = _Armed(["smua"])
    window._source_disconnect_confirmation = None
    _invalidate()(window)
    assert window._source_disconnect_confirmation is None
