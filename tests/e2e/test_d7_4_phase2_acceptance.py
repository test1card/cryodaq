"""D7.4 Phase-2: full acceptance surface over real ZMQ sockets.

Covers Codex acceptance requirements 2-5 via:
  T1  — Mixed-batch exact-once, no invented identity, no reorder
  T2  — Both launch paths drive real drain; static regression guards
  T3  — Restart invalidation (behavioural + static for all 5 call sites)
  T4  — Shutdown settles cleanly; lifecycle race, repeat ≥3 times
  T5  — Regression-fail guardrails (folded into T1–T4; documented below)

Hard rules enforced here:
- Real production ZeroMQ sockets + real ZmqBridge subprocess only.
- No time.sleep as a sync primitive — bounded-deadline polling via harness.
- No production source edits.
- Python 3.12+, ruff-clean.
"""

from __future__ import annotations

import ast
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.channels.descriptors import (
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.descriptor_transport import (
    DescriptorEnvelopeIssue,
    DescriptorQualifiedReading,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.state.descriptor_store import (
    DescriptorStore,
    IdentityStatus,
)
from cryodaq.gui.zmq_client import ZmqBridge
from tests.e2e._zmq_harness import (
    ZmqHarness,
    allocate_pub_addr,
    encode_descriptor_envelope,
    zmq_harness,  # noqa: F401 — pytest discovery
)

# ---------------------------------------------------------------------------
# Worktree root (for static source assertions)
# ---------------------------------------------------------------------------
_WT = Path(__file__).parents[2]  # tests/e2e/ -> tests/ -> <worktree-root>


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    from PySide6.QtCore import QTimer

    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _make_reading(
    *,
    channel: str,
    instrument_id: str = "test_inst",
    unit: str = "K",
    value: float = 4.2,
) -> Reading:
    return Reading(
        timestamp=datetime.now(tz=UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
    )


def _make_descriptor_for(reading: Reading, *, revision: int = 1):
    """Build a matching ChannelDescriptorV1 for a Reading."""
    from cryodaq.channels.descriptors import ChannelDescriptorV1

    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=reading.channel,
        instrument_id=reading.instrument_id,
        source_key="test.sensor",
        quantity=ChannelQuantity.TEMPERATURE,
        unit=reading.unit,
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="test_group",
        display_name="Test Channel",
        visible_by_default=True,
        display_order=0,
        descriptor_revision=revision,
    )


def _encode_envelope(reading: Reading, *, revision: int = 1) -> bytes:
    """Return production-encoded descriptor envelope bytes for reading.

    Delegates to the production PersistedChannelEnvelopeV1.from_descriptor path
    (same as encode_descriptor_envelope in the Phase-1 harness).
    """
    descriptor = _make_descriptor_for(reading, revision=revision)
    return encode_descriptor_envelope(descriptor)


def _recording_window() -> tuple[MainWindowV2, list[Reading]]:
    """Return a MainWindowV2 + fresh call-recorder list.

    Callers wrap with ``patch.object(w, "_dispatch_reading", side_effect=calls.append)``
    to record every _dispatch_reading call without modifying the instance.
    """
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    calls: list[Reading] = []
    return w, calls


def _find_poll_readings_bare_calls(source: str) -> list[int]:
    """Return line numbers of bare poll_readings() calls (not _with_descriptor)."""
    return _find_poll_readings_bare_calls_in(ast.parse(source))


def _find_poll_readings_bare_calls_in(node: ast.AST) -> list[int]:
    """Line numbers of bare poll_readings() calls in this AST subtree."""
    hits: list[int] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "poll_readings":
            hits.append(n.lineno)
    return hits


def _find_function_def(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the first (possibly NESTED) function def named ``name``, or None.

    Walks the whole tree so a closure defined inside another function (e.g. app.py's
    ``_tick`` inside ``main()``) is found.  This lets a static check be scoped to a
    single function body so matching calls ELSEWHERE in the file cannot mask a
    regression inside the target function.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def _calls_named_in(node: ast.AST, attr: str) -> bool:
    """True if the subtree contains a function or method call named ``attr``."""
    return any(
        isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Attribute) and n.func.attr == attr)
            or (isinstance(n.func, ast.Name) and n.func.id == attr)
        )
        for n in ast.walk(node)
    )


def _reconnect_sentinel_gate(harness: ZmqHarness, *, timeout_s: float = 20.0) -> None:
    """Re-establish the SUB subscription after a real bridge restart.

    The publisher's PUB socket persists across a bridge (SUB subprocess) restart,
    but the freshly spawned SUB must reconnect + re-subscribe before any published
    message is delivered (ZMQ connect() is non-blocking; pre-subscription messages
    are silently dropped).  This mirrors the Phase-1 harness sentinel gate: it
    publishes a sentinel on a loop and drains via the REAL bridge until one arrives.

    FIX-C(2): every poll drains the WHOLE batch and we assert no NON-sentinel reading
    is present.  Only sentinel readings are published here (the caller publishes its
    real test readings AFTER this gate returns), so a non-sentinel item at this point
    would mean a real reading leaked/was reordered into the gate window — we fail
    loudly rather than silently discarding it and masking a lost reading.

    Bounded-deadline polling: the short time.sleep is a poll interval INSIDE a
    deadline loop that checks a real arrival condition, not a sync primitive.
    """
    sentinel_ch = "e2e.p2.reconnect.sentinel"
    sentinel_r = _make_reading(channel=sentinel_ch, value=0.0)
    deadline = time.monotonic() + timeout_s
    arrived = False
    while time.monotonic() < deadline and not arrived:
        harness.publish(sentinel_r, descriptor_envelope=None)
        time.sleep(0.1)  # poll interval — SUB RCVTIMEO is 100 ms
        batch = harness.bridge.poll_readings_with_descriptor()
        non_sentinel = [qr for qr in batch if qr.reading.channel != sentinel_ch]
        assert not non_sentinel, (
            "Reconnect gate drained a NON-sentinel reading it would otherwise discard: "
            f"{[qr.reading.channel for qr in non_sentinel]}. This must not silently mask a lost reading."
        )
        if any(qr.reading.channel == sentinel_ch for qr in batch):
            arrived = True
    assert arrived, "Reconnect sentinel never arrived: restarted SUB did not re-subscribe within deadline"


def _drain_via(poll_fn, predicate, *, timeout_s: float = 15.0, poll_interval_s: float = 0.02) -> bool:
    """Call ``poll_fn()`` on a bounded-deadline loop until ``predicate()`` is True.

    ``poll_fn`` is invoked for its side effects (e.g. the real _poll_bridge_data
    drain loop, or the production _tick sequence); ``predicate`` inspects recorded
    state.  Returns True if the predicate became True within the deadline, else
    False.

    Bounded-deadline polling: the short time.sleep is a poll interval between real
    drain attempts inside a deadline loop, not a sync primitive.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        poll_fn()
        if predicate():
            return True
        time.sleep(poll_interval_s)
    return predicate()


# ---------------------------------------------------------------------------
# T1 — MIXED BATCH: exact-once, no invented identity, no reorder (Codex req 2)
# ---------------------------------------------------------------------------


def test_t1_mixed_batch_exact_once_no_invented_identity(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """Publish an interleaved mixed batch over real ZMQ; assert Codex req 2.

    Mix:
      - AUTHORITATIVE: valid descriptor-bearing channel, 2 readings
      - LEGACY_ABSENT:  legacy channel (no envelope), 2 readings
      - DUPLICATE/IDEMPOTENT: same descriptor republished on auth channel, 1 more reading
      - MALFORMED/REFUSED: corrupt envelope bytes → descriptor_issue=MALFORMED → REFUSED
      - CAPACITY_EXHAUSTED: fill store to capacity with small max_entries, then one more
        distinct channel with valid descriptor → CAPACITY_EXHAUSTED, reading still dispatched

    Regression kills covered (T5):
      - double-dispatch: exact_once assertion
      - invented identity: malformed channel never AUTHORITATIVE
      - bypassed store: each channel's identity_status checked explicitly
    """
    _app()

    # Channel definitions
    ch_auth = "e2e.p2.auth"
    ch_legacy = "e2e.p2.legacy"
    ch_malformed = "e2e.p2.malformed"

    r_auth_1 = _make_reading(channel=ch_auth, value=1.0)
    r_auth_2 = _make_reading(channel=ch_auth, value=2.0)
    r_auth_dup = _make_reading(channel=ch_auth, value=3.0)  # same descriptor → stays AUTHORITATIVE

    r_legacy_1 = _make_reading(channel=ch_legacy, value=10.0)
    r_legacy_2 = _make_reading(channel=ch_legacy, value=11.0)

    r_malformed = _make_reading(channel=ch_malformed, value=99.0)

    valid_env = _encode_envelope(r_auth_1)
    corrupt_env = b"\xff\xfe NOT-VALID-JSON-ENVELOPE"

    # For capacity test: use a small store so we don't need MAX_CATALOG_DESCRIPTORS channels
    # We use max_entries=3 to fill with ch_auth, ch_legacy, ch_malformed, then overflow
    SMALL_MAX = 3
    ch_overflow = "e2e.p2.overflow"
    r_overflow = _make_reading(channel=ch_overflow, value=0.0)
    valid_env_overflow = _encode_envelope(r_overflow)

    # Total readings to publish (mixed interleaved):
    # auth×2, dup×1, legacy×2, malformed×1, overflow×1 = 7
    total = 7

    # Publish all over real socket
    zmq_harness.publish(r_auth_1, descriptor_envelope=valid_env)
    zmq_harness.publish(r_legacy_1, descriptor_envelope=None)
    zmq_harness.publish(r_auth_2, descriptor_envelope=valid_env)  # same descriptor
    zmq_harness.publish(r_malformed, descriptor_envelope=corrupt_env)
    zmq_harness.publish(r_legacy_2, descriptor_envelope=None)
    zmq_harness.publish(r_auth_dup, descriptor_envelope=valid_env)  # duplicate/idempotent
    zmq_harness.publish(r_overflow, descriptor_envelope=valid_env_overflow)

    # Drain via real bridge subprocess
    qualified_list = zmq_harness.drain_until(total, timeout_s=15.0)
    assert len(qualified_list) == total, f"Expected {total} qualified readings, got {len(qualified_list)}"

    # Feed into real MainWindowV2 with a small-capacity store
    w, dispatch_calls = _recording_window()
    # Patch descriptor store with small capacity to exercise CAPACITY_EXHAUSTED
    small_store = DescriptorStore(max_entries=SMALL_MAX)
    w._descriptor_store = small_store  # type: ignore[assignment]

    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in qualified_list:
            w.dispatch_qualified_reading(q)

    # ---- Assertion 1: every reading dispatched EXACTLY once (no loss, no double) ----
    assert len(dispatch_calls) == total, (
        f"Expected {total} _dispatch_reading calls (exact-once), got {len(dispatch_calls)}"
    )

    # ---- Assertion 2: COMPLETE interleaved dispatch order preserved (FIX-3) ----
    # ZMQ preserves message order on a single PUB->SUB connection, so the full
    # ordered (channel, value) list of ALL dispatched readings must equal the
    # exact publish order — not merely per-channel order.
    expected_order = [
        (ch_auth, 1.0),
        (ch_legacy, 10.0),
        (ch_auth, 2.0),
        (ch_malformed, 99.0),
        (ch_legacy, 11.0),
        (ch_auth, 3.0),
        (ch_overflow, 0.0),
    ]
    actual_order = [(r.channel, r.value) for r in dispatch_calls]
    assert actual_order == expected_order, (
        f"Full interleaved dispatch order must equal publish order.\nexpected={expected_order}\nactual={actual_order}"
    )

    # ---- Assertion 2b: per-channel ordering preserved (subsumed by 2, kept explicit) ----
    auth_dispatched = [r for r in dispatch_calls if r.channel == ch_auth]
    assert len(auth_dispatched) == 3
    assert [r.value for r in auth_dispatched] == [1.0, 2.0, 3.0], "Auth channel readings must arrive in publish order"

    legacy_dispatched = [r for r in dispatch_calls if r.channel == ch_legacy]
    assert len(legacy_dispatched) == 2
    assert [r.value for r in legacy_dispatched] == [10.0, 11.0]

    # ---- Assertion 3: AUTHORITATIVE channel is authoritative ----
    auth_status = small_store.identity_status(ch_auth)
    assert auth_status is IdentityStatus.AUTHORITATIVE, f"ch_auth must be AUTHORITATIVE, got {auth_status}"

    # ---- Assertion 4: LEGACY_ABSENT channel is legacy_absent, NOT authoritative ----
    legacy_status = small_store.identity_status(ch_legacy)
    assert legacy_status is IdentityStatus.LEGACY_ABSENT, f"ch_legacy must be LEGACY_ABSENT, got {legacy_status}"

    # ---- Assertion 5: MALFORMED/REFUSED: channel is REFUSED, never AUTHORITATIVE ----
    # Finding report: corrupt bytes produce descriptor_issue=MALFORMED via
    # decode_persisted_channel_envelope raising PersistedChannelEnvelopeError in
    # qualify_reading_descriptor (not via descriptor_envelope_malformed flag, which
    # is only set for wrong type or oversize). The REFUSED classification occurs.
    malformed_q = next(q for q in qualified_list if q.reading.channel == ch_malformed)
    assert malformed_q.descriptor_issue is DescriptorEnvelopeIssue.MALFORMED, (
        f"Corrupt envelope must produce descriptor_issue=MALFORMED; got {malformed_q.descriptor_issue!r}. "
        "FINDING: if this is None, corrupt bytes were silently dropped rather than flagged malformed."
    )
    malformed_status = small_store.identity_status(ch_malformed)
    assert malformed_status is IdentityStatus.REFUSED, (
        f"Malformed channel must be REFUSED, got {malformed_status}. "
        "It must NEVER be AUTHORITATIVE (no invented identity)."
    )

    # ---- Assertion 6: DUPLICATE/IDEMPOTENT: same descriptor → stays AUTHORITATIVE ----
    # After two identical descriptors, store must remain AUTHORITATIVE (not REFUSED for revision regression)
    assert auth_status is IdentityStatus.AUTHORITATIVE, (
        "Duplicate identical descriptor must keep channel AUTHORITATIVE (idempotent)"
    )

    # ---- Assertion 7: CAPACITY_EXHAUSTED → reading still dispatched ----
    # With SMALL_MAX=3 and ch_auth+ch_legacy+ch_malformed filling the store,
    # ch_overflow should hit CAPACITY_EXHAUSTED but its reading must still appear
    overflow_dispatched = [r for r in dispatch_calls if r.channel == ch_overflow]
    assert len(overflow_dispatched) == 1, "CAPACITY_EXHAUSTED channel reading must still be dispatched (not dropped)"
    # Store doesn't have an entry for overflow (capacity hit prevents entry creation)
    overflow_status = small_store.identity_status(ch_overflow)
    assert overflow_status is None, f"CAPACITY_EXHAUSTED channel must not have a store entry; got {overflow_status}"


def test_t1_mixed_batch_repeat_1(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """Repeat of T1 mixed batch for determinism verification (run 2)."""
    _run_t1_core(zmq_harness)  # noqa: F811


def test_t1_mixed_batch_repeat_2(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """Repeat of T1 mixed batch for determinism verification (run 3)."""
    _run_t1_core(zmq_harness)  # noqa: F811


def _run_t1_core(harness: ZmqHarness) -> None:
    """Lightweight repeated T1 core: auth + legacy + malformed, assert exact-once."""
    _app()
    ch_auth = "e2e.p2.t1r.auth"
    ch_legacy = "e2e.p2.t1r.legacy"
    ch_bad = "e2e.p2.t1r.bad"

    r_auth = _make_reading(channel=ch_auth, value=1.0)
    r_legacy = _make_reading(channel=ch_legacy, value=2.0)
    r_bad = _make_reading(channel=ch_bad, value=3.0)

    valid_env = _encode_envelope(r_auth)
    corrupt_env = b"\x00CORRUPT"

    harness.publish(r_auth, descriptor_envelope=valid_env)
    harness.publish(r_legacy, descriptor_envelope=None)
    harness.publish(r_bad, descriptor_envelope=corrupt_env)

    qualified_list = harness.drain_until(3, timeout_s=15.0)
    assert len(qualified_list) == 3

    w, dispatch_calls = _recording_window()
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in qualified_list:
            w.dispatch_qualified_reading(q)

    assert len(dispatch_calls) == 3, f"Exact-once: expected 3, got {len(dispatch_calls)}"
    assert w._descriptor_store.identity_status(ch_auth) is IdentityStatus.AUTHORITATIVE
    assert w._descriptor_store.identity_status(ch_legacy) is IdentityStatus.LEGACY_ABSENT
    assert w._descriptor_store.identity_status(ch_bad) is IdentityStatus.REFUSED


# ---------------------------------------------------------------------------
# T2 — BOTH LAUNCH PATHS drive real drain; static regression guards (Codex req)
# ---------------------------------------------------------------------------


def test_t2_launcher_path_real_drain(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """Launcher path: call real LauncherWindow._poll_bridge_data via minimal namespace.

    Builds a minimal namespace (no heavy __init__ — no engine subprocess, no tray)
    holding the REAL harness bridge + REAL MainWindowV2, then invokes the UNBOUND
    production _poll_bridge_data to exercise the real drain path.

    Production lines exercised:
      - LauncherWindow._poll_bridge_data (src/cryodaq/launcher.py ~line 1937)
        for qualified in self._bridge.poll_readings_with_descriptor(): ...
        then health / data_flow / command watchdog branches
      - LauncherWindow._on_reading_qt (lines ~1989-2003): isinstance guard,
        _reading_count increment, _main_window.dispatch_qualified_reading()

    T5 regression: _reading_count incremented for DQR; non-DQR object → dropped, not counted.
    """
    from cryodaq.launcher import LauncherWindow

    _app()
    ch = "e2e.p2.t2.launcher"
    r = _make_reading(channel=ch, value=7.0)
    valid_env = _encode_envelope(r)

    w, dispatch_calls = _recording_window()
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        # Build minimal namespace that mirrors the attributes _poll_bridge_data touches.
        min_self = SimpleNamespace(
            _bridge=zmq_harness.bridge,
            _main_window=w,
            _reading_count=0,
            _last_reading_time=0.0,
            _soak_bridge_handshake=None,
            _last_health_watchdog_restart=0.0,
            _last_cmd_watchdog_restart=0.0,
        )
        # _poll_bridge_data calls self._on_reading_qt(...) — bind the REAL production
        # method to min_self so the whole per-item route runs production code.
        min_self._on_reading_qt = LauncherWindow._on_reading_qt.__get__(min_self, LauncherWindow)

        # FIX-1: do NOT pre-drain. Publish the reading, then let the REAL
        # _poll_bridge_data drain loop pull it off the queue. Its production body
        #     for qualified in self._bridge.poll_readings_with_descriptor():
        #         self._on_reading_qt(qualified)
        # runs NON-EMPTY here. Suppress ONLY the restart branches so a slow-joiner
        # transient is_healthy()==False cannot trigger a bridge restart mid-poll.
        zmq_harness.publish(r, descriptor_envelope=valid_env)

        with (
            patch.object(zmq_harness.bridge, "is_healthy", return_value=True),
            patch.object(zmq_harness.bridge, "data_flow_stalled", return_value=False),
            patch.object(zmq_harness.bridge, "command_channel_stalled", return_value=False),
        ):
            # Repeatedly call the real production _poll_bridge_data (slow-joiner:
            # it may take several polls before the SUB delivers the reading).
            got = _drain_via(
                lambda: LauncherWindow._poll_bridge_data(min_self),
                lambda: len(dispatch_calls) >= 1,
                timeout_s=15.0,
            )

        # The reading was routed through the REAL _poll_bridge_data ->
        # _on_reading_qt -> _main_window.dispatch_qualified_reading exactly once.
        assert got, "Real _poll_bridge_data drain did not deliver the reading within deadline"
        assert len(dispatch_calls) == 1, (
            f"Real _poll_bridge_data must dispatch the reading exactly once; got {len(dispatch_calls)}"
        )
        assert min_self._reading_count == 1, "_reading_count must be incremented exactly once for the DQR"
        assert w._descriptor_store.identity_status(ch) is IdentityStatus.AUTHORITATIVE

        # Non-DQR object → real _on_reading_qt must drop it (not count it).
        LauncherWindow._on_reading_qt(min_self, object())
        assert min_self._reading_count == 1, "Non-DQR object must be dropped; _reading_count must not increment"
        assert len(dispatch_calls) == 1, "Non-DQR must not trigger dispatch_qualified_reading"


def test_t2_app_path_real_drain(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """App path: real OperatorSnapshotIngressOwner + real bridge + real MainWindowV2.

    Runs the documented production _tick sequence:
        for qualified in bridge.poll_readings_with_descriptor():
            window.dispatch_qualified_reading(qualified)
        snapshot_ingress.pump()

    Asserts exact-once dispatch and that snapshot_ingress coexists without exception.

    T5 regression: static assertion that app.py _tick calls poll_readings_with_descriptor
    and dispatch_qualified_reading and contains NO poll_readings( call.
    """
    from cryodaq.gui.app import _drain_bridge_readings
    from cryodaq.gui.state.operator_snapshot_ingress import OperatorSnapshotIngressOwner

    _app()
    ch = "e2e.p2.t2.app"
    r = _make_reading(channel=ch, value=5.0)
    valid_env = _encode_envelope(r)

    w, dispatch_calls = _recording_window()
    snapshot_ingress = OperatorSnapshotIngressOwner(zmq_harness.bridge, parent=w)
    snapshot_ingress.start()

    # app.py `_tick` is a closure defined inside main() and cannot be imported or
    # invoked directly, so this test drives its EXACT production drain sequence
    # against the real bridge (the faithful substitute); the static no-poll_readings
    # test guards the closure body itself.
    def _tick() -> None:
        _drain_bridge_readings(zmq_harness.bridge, w)
        snapshot_ingress.pump()  # must not raise

    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        # FIX-1: do NOT pre-drain. Publish, then run the production _tick sequence
        # inside a bounded-deadline loop until the reading arrives (slow-joiner).
        zmq_harness.publish(r, descriptor_envelope=valid_env)
        got = _drain_via(_tick, lambda: len(dispatch_calls) >= 1, timeout_s=15.0)

    assert got, "App path _tick sequence did not deliver the reading within deadline"
    assert len(dispatch_calls) == 1, "App path: exact-once dispatch via _tick sequence"
    assert w._descriptor_store.identity_status(ch) is IdentityStatus.AUTHORITATIVE

    snapshot_ingress.stop()


def test_t2_static_no_poll_readings_in_app_py() -> None:
    """Static (FIX-B, function-SCOPED): app.py main()._tick uses the descriptor drain.

    AST-locates the ``_tick`` closure inside ``main()`` and asserts ITS body (only):
      - calls poll_readings_with_descriptor,
      - calls dispatch_qualified_reading,
      - contains NO bare poll_readings() call.
    Scoping to _tick means a matching call elsewhere in app.py cannot mask a
    regression inside the production drain closure.

    T5 regression kill: fails if _tick regresses to bare poll_readings() drain.
    """
    app_py = _WT / "src" / "cryodaq" / "gui" / "app.py"
    source = app_py.read_text(encoding="utf-8")

    tick = _find_function_def(source, "_tick")
    assert tick is not None, "app.py main() must define a _tick data-drain closure (not found)"
    drain = _find_function_def(source, "_drain_bridge_readings")
    assert drain is not None, "app.py must define the production qualified-reading drain"
    assert _calls_named_in(tick, "_drain_bridge_readings"), (
        "app.py _tick must invoke the production qualified-reading drain"
    )

    assert _calls_named_in(drain, "poll_readings_with_descriptor"), (
        "app.py drain must call poll_readings_with_descriptor()"
    )
    assert _calls_named_in(drain, "dispatch_qualified_reading"), (
        "app.py drain must route via dispatch_qualified_reading()"
    )
    hits = _find_poll_readings_bare_calls_in(drain)
    assert hits == [], (
        f"app.py drain must not call bare poll_readings() at lines {hits}; use poll_readings_with_descriptor() only"
    )


def test_t2_static_no_poll_readings_in_launcher_py() -> None:
    """Static (FIX-B, method-SCOPED): launcher._poll_bridge_data uses descriptor drain.

    AST-locates the ``_poll_bridge_data`` method and asserts ITS body (only) calls
    poll_readings_with_descriptor, routes via dispatch_qualified_reading (directly or
    through its _on_reading_qt helper), and contains NO bare poll_readings() call.

    T5 regression kill: fails if _poll_bridge_data regresses to bare poll_readings().
    """
    launcher_py = _WT / "src" / "cryodaq" / "launcher.py"
    source = launcher_py.read_text(encoding="utf-8")

    poll = _find_function_def(source, "_poll_bridge_data")
    assert poll is not None, "launcher.py must define _poll_bridge_data (not found)"

    assert _calls_named_in(poll, "poll_readings_with_descriptor"), (
        "launcher _poll_bridge_data must call poll_readings_with_descriptor()"
    )
    # _poll_bridge_data routes each item through _on_reading_qt, which calls
    # dispatch_qualified_reading. Assert the dispatch reaches the window in the drain
    # path: either _poll_bridge_data or _on_reading_qt calls dispatch_qualified_reading.
    on_reading = _find_function_def(source, "_on_reading_qt")
    routes = _calls_named_in(poll, "dispatch_qualified_reading") or (
        on_reading is not None and _calls_named_in(on_reading, "dispatch_qualified_reading")
    )
    assert routes, "launcher drain path (_poll_bridge_data/_on_reading_qt) must route via dispatch_qualified_reading()"
    hits = _find_poll_readings_bare_calls_in(poll)
    assert hits == [], (
        f"launcher _poll_bridge_data must not call bare poll_readings() at lines {hits}; "
        "use poll_readings_with_descriptor() only"
    )


# ---------------------------------------------------------------------------
# T3 — RESTART INVALIDATION on all restart paths (Codex req 3)
# ---------------------------------------------------------------------------


def test_t3_behavioural_invalidate_then_requalify() -> None:
    """Behavioural: store invalidate→legacy-absent cannot restore authority; fresh descriptor can.

    Does NOT require real subprocess restart (that is nondeterministic).
    Tests the behavioural semantics of invalidate_descriptor_transport:
    - After AUTHORITATIVE, invalidation → REFUSED (transport disconnected)
    - Post-invalidation legacy-absent reading → identity stays REFUSED (cannot requalify via legacy)
    - Post-invalidation fresh AUTHORITATIVE descriptor → channel requalifies to AUTHORITATIVE

    T5 regression kill: post-restart non-authority assertion.
    """
    _app()
    ch = "e2e.p2.t3.requalify"
    r = _make_reading(channel=ch, value=1.0)

    w, dispatch_calls = _recording_window()
    store = w._descriptor_store

    # Step (a): Establish AUTHORITATIVE via a qualified reading with valid descriptor
    qualified_auth = DescriptorQualifiedReading(
        reading=r,
        descriptor=_make_descriptor_for(r),
        descriptor_issue=None,
    )
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        w.dispatch_qualified_reading(qualified_auth)

    assert store.identity_status(ch) is IdentityStatus.AUTHORITATIVE, (
        "Channel must be AUTHORITATIVE before invalidation"
    )

    # Step (b): Invalidate (simulates bridge restart)
    w.invalidate_descriptor_transport()

    # After invalidation the store marks all entries REFUSED (transport disconnected)
    post_invalidate_status = store.identity_status(ch)
    assert post_invalidate_status is IdentityStatus.REFUSED, (
        f"After invalidate_descriptor_transport, channel must be REFUSED, got {post_invalidate_status}. "
        "T5: skipped invalidation would leave it AUTHORITATIVE."
    )

    # Step (c): Post-restart legacy-absent reading CANNOT restore AUTHORITATIVE
    # (once REFUSED, _process_legacy_absent returns early if status is REFUSED)
    legacy_q = DescriptorQualifiedReading(
        reading=_make_reading(channel=ch, value=2.0),
        descriptor=None,
        descriptor_issue=None,
    )
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        w.dispatch_qualified_reading(legacy_q)

    post_legacy_status = store.identity_status(ch)
    assert post_legacy_status is not IdentityStatus.AUTHORITATIVE, (
        f"Post-restart legacy-absent reading must NOT restore AUTHORITATIVE; got {post_legacy_status}. "
        "T5: this would indicate invalidation is not blocking legacy requalification."
    )

    # Step (d): Fresh valid descriptor CAN requalify
    r2 = _make_reading(channel=ch, value=3.0)
    fresh_q = DescriptorQualifiedReading(
        reading=r2,
        descriptor=_make_descriptor_for(r2, revision=2),  # new revision → requalify
        descriptor_issue=None,
    )
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        w.dispatch_qualified_reading(fresh_q)

    requalified_status = store.identity_status(ch)
    assert requalified_status is IdentityStatus.AUTHORITATIVE, (
        f"After fresh valid descriptor post-restart, channel must requalify to AUTHORITATIVE; got {requalified_status}"
    )

    # All 3 readings dispatched
    assert len(dispatch_calls) == 3, (
        f"All 3 readings must be dispatched regardless of identity status; got {len(dispatch_calls)}"
    )


def _is_bridge_start_call(node: ast.AST) -> bool:
    """True if node is a ``bridge.start()`` / ``self._bridge.start()`` call."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr != "start":
        return False
    val = node.func.value
    val_name = val.attr if isinstance(val, ast.Attribute) else val.id if isinstance(val, ast.Name) else ""
    return "bridge" in val_name.lower()


def _is_invalidate_call(node: ast.AST) -> bool:
    """True if node is an ``…invalidate_descriptor_transport()`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"invalidate_descriptor_transport", "_invalidate_descriptor_transport"}
    )


def _is_bridge_shutdown_call(node: ast.AST) -> bool:
    """True if node is a ``bridge.shutdown()`` / ``self._bridge.shutdown()`` call."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr != "shutdown":
        return False
    val = node.func.value
    val_name = val.attr if isinstance(val, ast.Attribute) else val.id if isinstance(val, ast.Name) else ""
    return "bridge" in val_name.lower()


def _iter_stmt_blocks(tree: ast.AST) -> list[list[ast.stmt]]:
    """All statement-list blocks (body/orelse/finalbody) in the tree."""
    blocks: list[list[ast.stmt]] = []
    for child in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(child, field, None)
            if isinstance(block, list) and block and all(isinstance(s, ast.stmt) for s in block):
                blocks.append(block)
    return blocks


def _innermost_block_of(target: ast.AST, blocks: list[list[ast.stmt]]) -> list[ast.stmt] | None:
    """Innermost block directly enclosing target (smallest containing-statement span).

    A call's innermost block is the branch it physically lives in.  Because we pick
    the SMALLEST-span enclosing statement, a shutdown()/invalidate() nested inside a
    deeper sub-block (e.g. a nested FunctionDef like main()._tick) is attributed to
    that deeper block, NOT to the outer function body — so an initial spawn in
    main()'s body is not contaminated by shutdowns inside its nested _tick closure.
    """
    best: list[ast.stmt] | None = None
    best_span: int | None = None
    for block in blocks:
        for stmt in block:
            lo = stmt.lineno
            hi = getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno
            if lo <= target.lineno <= hi and any(n is target for n in ast.walk(stmt)):
                span = hi - lo
                if best_span is None or span < best_span:
                    best_span, best = span, block
    return best


def _enclosing_branch_body(target: ast.AST, blocks: list[list[ast.stmt]]) -> list[ast.stmt] | None:
    """The innermost statement-list (branch body) that DIRECTLY contains target.

    "Directly contains" = target is inside a top-level statement of this block and is
    NOT inside a deeper block of a *different* compound statement's nested branch.
    Returns the body list of the nearest enclosing ``if``/``for``/``while``/``try``/
    function whose own body/orelse/finalbody directly holds the statement wrapping
    target.  This is the mutual-exclusion unit: sibling ``elif``/``else`` branches are
    DIFFERENT body lists, so an invalidate in a sibling branch is not in this body.
    """
    return _innermost_block_of(target, blocks)


def _restart_starts_with_block_invalidates(source: str) -> list[tuple[int, list[int], bool]]:
    """Return (start_line, invalidate_lines_in_same_branch, branch_has_shutdown).

    For each ``bridge.start()`` we take its enclosing branch body (innermost
    directly-containing statement list) and then search that branch's ENTIRE subtree
    for invalidate_descriptor_transport() and bridge.shutdown() calls.  Searching the
    subtree (not just the direct statements) means a guarded call such as
    ``if self._main_window is not None: self._main_window.invalidate_descriptor_transport()``
    still counts for a start() in the same branch — while a sibling ``elif`` branch,
    being a DIFFERENT body list, does not.  That is exactly the mutual-exclusion the
    reviewer requires: dropping the invalidate from one branch cannot be masked by an
    invalidate hoisted into a sibling branch.
    """
    tree = ast.parse(source)
    blocks = _iter_stmt_blocks(tree)

    def _subtree_of_block(block: list[ast.stmt]):
        """Walk the branch subtree but DO NOT descend into nested function defs.

        This keeps a nested closure's calls (e.g. main()._tick's shutdown/invalidate)
        out of the enclosing function body's scan, so an initial spawn in main()/
        __init__ is not contaminated by restart calls living in a nested function.
        A nested FunctionDef node is itself yielded (harmless) but its body is not
        descended into.
        """
        stack: list[ast.AST] = list(block)
        while stack:
            node = stack.pop()
            yield node
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue  # do not descend into a nested function's body
            stack.extend(ast.iter_child_nodes(node))

    results: list[tuple[int, list[int], bool]] = []
    for node in ast.walk(tree):
        if not _is_bridge_start_call(node):
            continue
        branch = _enclosing_branch_body(node, blocks)
        if branch is None:
            results.append((node.lineno, [], False))
            continue
        invalidate_lines: list[int] = []
        shutdown_lines: list[int] = []
        for inner in _subtree_of_block(branch):
            if _is_invalidate_call(inner):
                invalidate_lines.append(inner.lineno)
            elif _is_bridge_shutdown_call(inner):
                shutdown_lines.append(inner.lineno)
        # A RESTART branch is one where a bridge.shutdown() PRECEDES the start()
        # (restart pattern: shutdown -> invalidate -> start).  A trailing shutdown
        # in an error/except path AFTER an initial start() (e.g. launcher.__init__'s
        # soak-handshake failure cleanup) is NOT a restart and stays excluded.
        has_preceding_shutdown = any(sl < node.lineno for sl in shutdown_lines)
        results.append((node.lineno, sorted(invalidate_lines), has_preceding_shutdown))
    return sorted(results)


def test_t3_static_all_five_invalidate_before_start() -> None:
    """Static (BRANCH-aware, AST): every restart branch invalidates BEFORE start().

    The 5 restart sites are:
      app.py   (2): main()._tick is_healthy restart, main()._tick data_flow_stalled restart
      launcher (3): _poll_bridge_data health watchdog, _poll_bridge_data cmd watchdog,
                    _restart_engine

    FIX-A: association is BRANCH-level (in-BLOCK), not function-level.  For every
    ``bridge.start()`` we find its innermost statement block (the ``if``/``elif``/
    ``else``/function body it physically lives in) and require an
    ``invalidate_descriptor_transport()`` at a LOWER line IN THAT SAME BLOCK.  A
    restart branch is identified by a sibling ``bridge.shutdown()`` in the same block
    (restart pattern = shutdown -> invalidate -> start); an initial spawn block has a
    start() but no shutdown() and is excluded.

    Why this kills the reviewer's regression (proved by a synthetic mutation in
    test_t3_fix_a_branch_awareness_regression_guard): hoisting a DUPLICATE invalidate
    into the health branch while DROPPING the command-branch invalidate leaves the
    command branch's start() in a block with a shutdown() but NO in-block invalidate,
    so the per-branch ordering assertion fails.  The old function-level sorted pairing
    masked this because the health branch's extra invalidate satisfied the count.

    ROLE (FIX-E/FIX-F, honest coverage picture): this is a SECONDARY net, not the
    primary proof.  The PRIMARY proof is BEHAVIORAL and end-to-end over real sockets:
      - all THREE launcher restart triggers are behaviorally proven —
        test_t3_real_restart_via_poll_bridge_data (health/data-flow watchdog),
        test_t3_real_restart_via_command_watchdog (command watchdog), and
        test_t3_real_restart_via_restart_engine (_restart_engine).  Each proves a
        real bridge restart (restart_count()+1) AND the invalidate-BEFORE-start
        ORDERING: a wrapper around the REAL bridge.start() captures channel X's
        identity_status at the instant production invokes start() and asserts X was
        already invalidated then — a mutation moving invalidate after start() fails.
        Each also proves the full invalidate -> legacy-cannot-requalify ->
        fresh-descriptor-requalifies store contract.
      - the app.py main()._tick restart branches (x2) are the SAME triggers in the
        standalone-GUI entry point; _tick is a closure inside main() that cannot be
        invoked without standing up the full GUI process, so they remain STATIC-ONLY,
        covered by this guard plus the behaviorally-proven shared store invariant.
        We do NOT overclaim app.py _tick as behavioral.
    KNOWN LIMITATION: static analysis cannot prove runtime reachability — e.g.
    ``if False: invalidate()`` would satisfy this AST check while never running.  We
    do NOT chase such unreachable-code constructs here (an unwinnable whack-a-mole);
    the behavioral tests are the real guarantee, and this guard only catches
    source-level drops of the invalidate call.
    """
    app_py = _WT / "src" / "cryodaq" / "gui" / "app.py"
    launcher_py = _WT / "src" / "cryodaq" / "launcher.py"

    _check_branch_level(app_py.read_text(encoding="utf-8"), "app.py", expected_restart_branches=2)
    _check_branch_level(launcher_py.read_text(encoding="utf-8"), "launcher.py", expected_restart_branches=3)


def _check_branch_level(source: str, label: str, expected_restart_branches: int) -> None:
    """Assert every restart-branch bridge.start() has an in-branch invalidate before it.

    Branch-level (in-BRANCH-subtree) association via
    _restart_starts_with_block_invalidates.  A restart branch = a branch where a
    bridge.shutdown() PRECEDES the start() (pattern: shutdown -> invalidate -> start).
    An initial-spawn start() (no preceding in-branch shutdown — e.g. app.main() body,
    or launcher.__init__'s else-branch whose only shutdown is a trailing except-path
    cleanup) is excluded, but must also have no in-branch invalidate.  A restart
    start() must have an invalidate at a lower line in the SAME branch subtree.
    """
    restart_branches = 0
    for start_line, block_invalidates, has_shutdown in _restart_starts_with_block_invalidates(source):
        if not has_shutdown:
            # Initial, non-restart spawn (app.main() / launcher.__init__): correct to
            # have no in-block invalidate; guard that it indeed has none.
            assert not block_invalidates, (
                f"{label}: unexpected invalidate in a non-restart (initial-spawn) block "
                f"with bridge.start() at line {start_line}"
            )
            continue
        restart_branches += 1
        preceding = [iv for iv in block_invalidates if iv < start_line]
        assert preceding, (
            f"{label}: restart bridge.start() at line {start_line} has NO "
            f"invalidate_descriptor_transport() before it IN THE SAME BRANCH "
            f"(in-block invalidates: {block_invalidates}). "
            "T5/FIX-A: a restart branch dropped its invalidation."
        )

    assert restart_branches == expected_restart_branches, (
        f"{label}: expected exactly {expected_restart_branches} restart branches "
        f"(shutdown+invalidate+start); found {restart_branches}. "
        "T5: a dropped restart branch changes this count."
    )


def test_t3_fix_a_branch_awareness_regression_guard() -> None:
    """FIX-A meta-test: the branch-aware static check catches the reviewer's regression.

    Reviewer's bug in the OLD function-level check: hoisting a DUPLICATE invalidate
    into the health branch while DROPPING the command-branch invalidate still passed
    (invalidate count matched start count function-wide, and each start had SOME
    lower-line invalidate in the function).  This meta-test drives _check_branch_level
    against synthetic sources to prove the new BRANCH-level check rejects that.
    """
    import pytest

    # The exact reviewer regression: two watchdog branches; the health branch keeps
    # (even duplicates) its invalidate, the command branch DROPS its invalidate.
    reviewer_regression = (
        "def _poll_bridge_data(self):\n"
        "    if unhealthy or stalled:\n"
        "        self._bridge.shutdown()\n"
        "        if self._main_window is not None:\n"
        "            self._main_window.invalidate_descriptor_transport()\n"
        "            self._main_window.invalidate_descriptor_transport()\n"
        "        self._bridge.start()\n"
        "        return\n"
        "    if self._bridge.command_channel_stalled():\n"
        "        self._bridge.shutdown()\n"
        "        self._bridge.start()\n"
        "        return\n"
    )
    with pytest.raises(AssertionError, match="NO .*invalidate"):
        _check_branch_level(reviewer_regression, "reviewer_regression", expected_restart_branches=2)

    # Well-formed twin: each restart branch keeps its own invalidate -> passes.
    well_formed = (
        "def _poll_bridge_data(self):\n"
        "    if unhealthy or stalled:\n"
        "        self._bridge.shutdown()\n"
        "        if self._main_window is not None:\n"
        "            self._main_window.invalidate_descriptor_transport()\n"
        "        self._bridge.start()\n"
        "        return\n"
        "    if self._bridge.command_channel_stalled():\n"
        "        self._bridge.shutdown()\n"
        "        if self._main_window is not None:\n"
        "            self._main_window.invalidate_descriptor_transport()\n"
        "        self._bridge.start()\n"
        "        return\n"
    )
    _check_branch_level(well_formed, "well_formed", expected_restart_branches=2)

    # Ordering regression: invalidate AFTER start in the branch -> must fail.
    invalidate_after_start = (
        "def _restart_engine(self):\n"
        "    self._bridge.shutdown()\n"
        "    self._bridge.start()\n"
        "    if self._main_window is not None:\n"
        "        self._main_window.invalidate_descriptor_transport()\n"
    )
    with pytest.raises(AssertionError, match="NO .*invalidate"):
        _check_branch_level(invalidate_after_start, "invalidate_after_start", expected_restart_branches=1)

    # Initial spawn with a trailing except-path shutdown (launcher.__init__ shape) is
    # excluded (not a restart), and the one real restart branch is counted -> passes.
    init_with_except_shutdown = (
        "def __init__(self):\n"
        "    if failed:\n"
        "        pass\n"
        "    else:\n"
        "        self._bridge.start()\n"
        "        try:\n"
        "            self.emit()\n"
        "        except Exception:\n"
        "            self._bridge.shutdown()\n"
        "            raise\n"
        "    def _tick(self):\n"
        "        if not self._bridge.is_healthy():\n"
        "            self._bridge.shutdown()\n"
        "            if self._main_window is not None:\n"
        "                self._main_window.invalidate_descriptor_transport()\n"
        "            self._bridge.start()\n"
    )
    _check_branch_level(init_with_except_shutdown, "init_with_except_shutdown", expected_restart_branches=1)


def test_t3_real_socket_invalidate_requalify_via_bridge(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """Real-socket behavioural: invalidate → legacy-absent REFUSED → requalify AUTHORITATIVE.

    Publishes over real ZMQ, feeds into real window, invalidates, publishes legacy-absent
    on same channel, confirms REFUSED, then publishes valid descriptor again and confirms
    AUTHORITATIVE.
    """
    _app()
    ch = "e2e.p2.t3.real"

    r1 = _make_reading(channel=ch, value=1.0)
    valid_env = _encode_envelope(r1)

    # Publish and drain: establish AUTHORITATIVE
    zmq_harness.publish(r1, descriptor_envelope=valid_env)
    ql1 = zmq_harness.drain_until(1, timeout_s=15.0)

    w, dispatch_calls = _recording_window()
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql1:
            w.dispatch_qualified_reading(q)

    assert w._descriptor_store.identity_status(ch) is IdentityStatus.AUTHORITATIVE
    # FIX-C(1): exact count — the first publish dispatches exactly once.
    assert len(dispatch_calls) == 1, f"Step 1 must dispatch exactly once; got {len(dispatch_calls)}"

    # Invalidate (simulates bridge restart)
    w.invalidate_descriptor_transport()
    assert w._descriptor_store.identity_status(ch) is IdentityStatus.REFUSED

    # Publish legacy-absent reading on same channel
    r2 = _make_reading(channel=ch, value=2.0)
    zmq_harness.publish(r2, descriptor_envelope=None)
    ql2 = zmq_harness.drain_until(1, timeout_s=15.0)

    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql2:
            w.dispatch_qualified_reading(q)

    # Must NOT be AUTHORITATIVE after legacy-absent post-invalidation
    post_legacy = w._descriptor_store.identity_status(ch)
    assert post_legacy is not IdentityStatus.AUTHORITATIVE, (
        f"Post-invalidation legacy-absent must NOT restore AUTHORITATIVE; got {post_legacy}"
    )
    # FIX-C(1): exact count — the legacy-absent publish dispatches exactly once more.
    assert len(dispatch_calls) == 2, f"Step 2 must bring total to exactly 2; got {len(dispatch_calls)}"

    # Publish fresh valid descriptor — must requalify
    r3 = _make_reading(channel=ch, value=3.0)
    valid_env_v2 = _encode_envelope(r3, revision=2)
    zmq_harness.publish(r3, descriptor_envelope=valid_env_v2)
    ql3 = zmq_harness.drain_until(1, timeout_s=15.0)

    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql3:
            w.dispatch_qualified_reading(q)

    assert w._descriptor_store.identity_status(ch) is IdentityStatus.AUTHORITATIVE, (
        "Fresh valid descriptor post-restart must requalify channel to AUTHORITATIVE"
    )

    # FIX-C(1): exact total — precisely 3 dispatches, one per publish, no loss/dup.
    assert len(dispatch_calls) == 3, f"Exactly 3 total dispatches expected; got {len(dispatch_calls)}"
    assert [r.value for r in dispatch_calls] == [1.0, 2.0, 3.0], (
        f"Dispatch order/values must be exactly [1.0, 2.0, 3.0]; got {[r.value for r in dispatch_calls]}"
    )


# ---------------------------------------------------------------------------
# T3 restart-path coverage — ACCURATE PICTURE (FIX-E, FIX-F):
#
# All THREE launcher restart triggers are PROVEN BEHAVIORALLY end-to-end over
# real sockets. Each proves the FULL ordering contract, not merely that invalidate
# ran: a wrapper around the REAL bridge.start() captures channel X's identity_status
# at the INSTANT production invokes start(), and we assert X was ALREADY invalidated
# at that moment (FIX-F) — so a mutation moving invalidate AFTER start() fails.
# Each also proves: restart_count()+1 (a real subprocess restart happened), and the
# store contract invalidate -> legacy-cannot-requalify -> fresh-descriptor-requalifies:
#     1. _poll_bridge_data HEALTH/DATA-FLOW watchdog branch
#        (test_t3_real_restart_via_poll_bridge_data)
#     2. _poll_bridge_data COMMAND-channel watchdog branch
#        (test_t3_real_restart_via_command_watchdog)
#     3. _restart_engine (test_t3_real_restart_via_restart_engine) — engine/timer
#        side stubbed, bridge + window REAL.
#
# The app.py main()._tick restart branches (x2) are the SAME triggers in the
# standalone-GUI entry point.  _tick is a closure inside main() that cannot be
# invoked without standing up the full GUI process, so they remain STATIC-ONLY,
# covered by:
#   (a) the shared store invariant proven behaviorally above (identical contract),
#       and
#   (b) the branch-aware static AST guard (test_t3_static_all_five_invalidate_
#       before_start), which is a SECONDARY net.
# The AST guard's known limitation: static analysis cannot prove runtime
# reachability (e.g. `if False: invalidate()` would defeat any line/subtree check).
# The PRIMARY proof is behavioral; the AST guard only catches source-level drops.
# We do NOT overclaim app.py _tick as behavioral — it is static + shared-invariant.
# ---------------------------------------------------------------------------


def _run_real_restart_via_poll_bridge_data(
    harness: ZmqHarness,
    *,
    ch: str,
    trigger: str,
) -> None:
    """Drive a REAL launcher watchdog restart branch end-to-end over real sockets.

    ``trigger`` selects which real production restart branch runs:
      - "health": is_healthy() forced False -> health/data-flow watchdog branch.
      - "command": is_healthy True + command_channel_stalled True -> cmd watchdog.

    Both branches execute the REAL sequence: self._bridge.shutdown() ->
    self._main_window.invalidate_descriptor_transport() -> self._bridge.start().
    FIX-F: a wrapper around the REAL bridge.start captures X's identity_status at
    start()-entry and asserts it was already invalidated then, proving invalidate ran
    BEFORE start (not merely that it ran).
    """
    from cryodaq.launcher import LauncherWindow

    _app()
    w, dispatch_calls = _recording_window()

    # (a) Establish AUTHORITATIVE for channel X over the real socket.
    r1 = _make_reading(channel=ch, value=1.0)
    valid_env = _encode_envelope(r1)
    harness.publish(r1, descriptor_envelope=valid_env)
    ql1 = harness.drain_until(1, timeout_s=15.0)
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql1:
            w.dispatch_qualified_reading(q)
    assert w._descriptor_store.identity_status(ch) is IdentityStatus.AUTHORITATIVE, (
        "Channel X must be AUTHORITATIVE before the real restart"
    )
    # FIX-C(1): exact count — the pre-restart publish dispatches exactly once.
    assert len(dispatch_calls) == 1, f"Pre-restart must dispatch exactly once; got {len(dispatch_calls)}"

    restart_count_before = harness.bridge.restart_count()

    # (b) Minimal launcher namespace over the REAL harness bridge + REAL window.
    min_self = SimpleNamespace(
        _bridge=harness.bridge,
        _main_window=w,
        _reading_count=0,
        _last_reading_time=0.0,
        _last_health_watchdog_restart=float("-inf"),
        _last_cmd_watchdog_restart=float("-inf"),
    )
    # Bind the real _on_reading_qt so any queued reading drained by the real
    # _poll_bridge_data loop routes through production code (not just the restart branch).
    min_self._on_reading_qt = LauncherWindow._on_reading_qt.__get__(min_self, LauncherWindow)
    min_self._invalidate_descriptor_transport = LauncherWindow._invalidate_descriptor_transport.__get__(
        min_self, LauncherWindow
    )

    # (c) Force the chosen restart branch and call the REAL _poll_bridge_data once.
    if trigger == "health":
        health_patch = patch.object(harness.bridge, "is_healthy", return_value=False)
        cmd_patch = patch.object(harness.bridge, "command_channel_stalled", return_value=False)
    elif trigger == "command":
        health_patch = patch.object(harness.bridge, "is_healthy", return_value=True)
        cmd_patch = patch.object(harness.bridge, "command_channel_stalled", return_value=True)
    else:  # pragma: no cover - guard
        raise ValueError(f"unknown trigger {trigger!r}")

    # FIX-F: prove invalidate ran BEFORE start(), not merely that it ran. Wrap the
    # REAL bridge.start so that at the INSTANT production invokes it we capture the
    # store's identity_status for X, then delegate to the real start. A mutation that
    # moved invalidate AFTER start() would capture AUTHORITATIVE here and fail.
    real_start = harness.bridge.start
    start_entry: dict[str, object] = {}

    def _wrapped_start(*a: object, **k: object) -> object:
        start_entry["status_at_start"] = w._descriptor_store.identity_status(ch)
        return real_start(*a, **k)

    with (
        health_patch,
        patch.object(harness.bridge, "data_flow_stalled", return_value=False),
        cmd_patch,
        patch.object(harness.bridge, "start", side_effect=_wrapped_start),
    ):
        # The real branch runs: bridge.shutdown() + window.invalidate_descriptor_transport()
        # + bridge.start(). No pre-drained readings on this call.
        LauncherWindow._poll_bridge_data(min_self)

    # (d) A real restart occurred and invalidation ran BEFORE start(): X is no
    # longer AUTHORITATIVE immediately after the branch.
    assert harness.bridge.restart_count() == restart_count_before + 1, (
        "Real bridge restart (shutdown+start) must have occurred in the watchdog branch"
    )
    # FIX-F: the wrapper actually ran, and at start() entry X was ALREADY invalidated.
    assert "status_at_start" in start_entry, "bridge.start() was never invoked by the restart branch"
    assert start_entry["status_at_start"] is not IdentityStatus.AUTHORITATIVE, (
        "invalidate_descriptor_transport() must run BEFORE bridge.start(): at start() entry "
        f"channel X was {start_entry['status_at_start']!r} (expected already-invalidated). "
        "A mutation moving invalidate after start() would leave X AUTHORITATIVE here."
    )
    post_restart = w._descriptor_store.identity_status(ch)
    assert post_restart is not IdentityStatus.AUTHORITATIVE, (
        f"After the real restart, X must NOT be AUTHORITATIVE (invalidate ran before start); got {post_restart}"
    )
    # FIX-C(1): the restart branch drained no readings — dispatch count unchanged.
    assert len(dispatch_calls) == 1, (
        f"The restart-branch _poll_bridge_data call must dispatch nothing new; got {len(dispatch_calls)}"
    )

    # (e) Re-establish the SUB subscription against the restarted bridge, then a
    # legacy-absent reading on X must NOT restore AUTHORITATIVE.
    _reconnect_sentinel_gate(harness, timeout_s=20.0)
    r2 = _make_reading(channel=ch, value=2.0)
    harness.publish(r2, descriptor_envelope=None)
    ql2 = harness.drain_until(1, timeout_s=15.0)
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql2:
            w.dispatch_qualified_reading(q)
    post_legacy = w._descriptor_store.identity_status(ch)
    assert post_legacy is not IdentityStatus.AUTHORITATIVE, (
        f"Post-restart legacy-absent reading must NOT restore AUTHORITATIVE; got {post_legacy}"
    )
    # FIX-C(1): exact count — the post-restart legacy-absent publish dispatches once.
    assert len(dispatch_calls) == 2, f"Post-restart legacy publish must bring total to 2; got {len(dispatch_calls)}"

    # (f) A fresh valid descriptor (revision 2) on X requalifies to AUTHORITATIVE.
    r3 = _make_reading(channel=ch, value=3.0)
    valid_env_v2 = _encode_envelope(r3, revision=2)
    harness.publish(r3, descriptor_envelope=valid_env_v2)
    ql3 = harness.drain_until(1, timeout_s=15.0)
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql3:
            w.dispatch_qualified_reading(q)
    assert w._descriptor_store.identity_status(ch) is IdentityStatus.AUTHORITATIVE, (
        "Fresh valid descriptor after the real restart must requalify X to AUTHORITATIVE"
    )
    # FIX-C(1): exact total — precisely 3 dispatches (one per publish), in order.
    assert len(dispatch_calls) == 3, f"Exactly 3 total dispatches expected; got {len(dispatch_calls)}"
    assert [r.value for r in dispatch_calls] == [1.0, 2.0, 3.0], (
        f"Dispatch order/values must be exactly [1.0, 2.0, 3.0]; got {[r.value for r in dispatch_calls]}"
    )


def test_t3_real_restart_via_poll_bridge_data(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """End-to-end: REAL launcher HEALTH/DATA-FLOW watchdog restart over real sockets.

    Drives LauncherWindow._poll_bridge_data's health-watchdog branch, which calls
    the REAL bridge.shutdown() + window.invalidate_descriptor_transport() + REAL
    bridge.start(). Proves (via a start()-entry capture, FIX-F) that invalidate ran
    BEFORE start, that a post-restart legacy-absent reading cannot requalify, and a
    fresh descriptor can.
    """
    _run_real_restart_via_poll_bridge_data(zmq_harness, ch="e2e.p2.t3.realrestart.health", trigger="health")


def test_t3_real_restart_via_command_watchdog(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """End-to-end: REAL launcher COMMAND-channel watchdog restart over real sockets.

    Drives LauncherWindow._poll_bridge_data's command-watchdog branch (is_healthy
    True, command_channel_stalled True), which also does a REAL shutdown +
    invalidate + start. Same invalidate-BEFORE-start ordering (start()-entry capture,
    FIX-F) and invalidate->requalify semantics proven behaviourally.
    """
    _run_real_restart_via_poll_bridge_data(zmq_harness, ch="e2e.p2.t3.realrestart.cmd", trigger="command")


def test_t3_real_restart_via_restart_engine(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """End-to-end: REAL launcher _restart_engine (3rd restart trigger) over real sockets.

    Drives the REAL ``LauncherWindow._restart_engine`` bound to a minimal namespace.
    The bridge lifecycle is REAL — the production sequence
        self._bridge.shutdown() -> self._stop_engine() -> time.sleep(1) ->
        self._start_engine() -> self._main_window.invalidate_descriptor_transport()
        -> self._bridge.start()
    runs against the REAL harness bridge and REAL MainWindowV2.

    STUBBED (and why): only the engine-subprocess + Qt-timer side is stubbed —
      - _clear_engine_down_banner / _stop_engine / _start_engine : these spawn or
        talk to the ENGINE subprocess, which this real-socket bridge test does not
        stand up (the harness publisher plays the engine's PUB role).
      - _data_timer / _health_timer : Qt QTimer objects owned by the heavy
        LauncherWindow.__init__ we deliberately skip; stubbed as no-op .stop()/.start().
    The REAL bits kept: _bridge (real ZmqBridge subprocess) and _main_window (real
    MainWindowV2 with its real DescriptorStore). Production _restart_engine calls
    time.sleep(1) internally — that is PRODUCTION code (a one-time ~1s cost), not a
    test synchronisation primitive.
    """
    from unittest.mock import MagicMock

    from cryodaq.launcher import LauncherWindow

    _app()
    ch = "e2e.p2.t3.realrestart.engine"
    w, dispatch_calls = _recording_window()

    # (a) Establish AUTHORITATIVE for channel X over the real socket.
    r1 = _make_reading(channel=ch, value=1.0)
    valid_env = _encode_envelope(r1)
    zmq_harness.publish(r1, descriptor_envelope=valid_env)
    ql1 = zmq_harness.drain_until(1, timeout_s=15.0)
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql1:
            w.dispatch_qualified_reading(q)
    assert w._descriptor_store.identity_status(ch) is IdentityStatus.AUTHORITATIVE, (
        "Channel X must be AUTHORITATIVE before _restart_engine"
    )
    assert len(dispatch_calls) == 1, f"Pre-restart must dispatch exactly once; got {len(dispatch_calls)}"

    restart_count_before = zmq_harness.bridge.restart_count()

    # (b) Minimal namespace: REAL bridge + REAL window; engine/timer bits stubbed.
    min_self = SimpleNamespace(
        _bridge=zmq_harness.bridge,  # REAL
        _main_window=w,  # REAL
        # settable attrs _restart_engine assigns (values irrelevant, must exist)
        _restart_giving_up=True,
        _restart_attempts=3,
        _config_error_modal_shown=True,
        _restart_pending=True,
        _engine_external=True,
        # engine/timer bits: intentionally stubbed (see docstring)
        _clear_engine_down_banner=MagicMock(name="_clear_engine_down_banner"),
        _stop_engine=MagicMock(name="_stop_engine"),
        _start_engine=MagicMock(name="_start_engine"),
        _data_timer=MagicMock(name="_data_timer"),
        _health_timer=MagicMock(name="_health_timer"),
    )
    min_self._invalidate_descriptor_transport = LauncherWindow._invalidate_descriptor_transport.__get__(
        min_self, LauncherWindow
    )

    # (c) Invoke the REAL production _restart_engine bound to min_self.
    # FIX-F: wrap the REAL bridge.start so that at the INSTANT production invokes it
    # we capture X's identity_status, then delegate to the real start. This proves
    # invalidate ran BEFORE start (not merely that it ran): a mutation moving
    # invalidate after start() would capture AUTHORITATIVE here and fail.
    real_start = zmq_harness.bridge.start
    start_entry: dict[str, object] = {}

    def _wrapped_start(*a: object, **k: object) -> object:
        start_entry["status_at_start"] = w._descriptor_store.identity_status(ch)
        return real_start(*a, **k)

    with patch.object(zmq_harness.bridge, "start", side_effect=_wrapped_start):
        LauncherWindow._restart_engine.__get__(min_self, LauncherWindow)()

    # (d) A REAL bridge restart happened via production _restart_engine, and
    # invalidation ran BEFORE start(): X is no longer AUTHORITATIVE.
    assert zmq_harness.bridge.restart_count() == restart_count_before + 1, (
        "Real bridge restart (shutdown+start) must have occurred via _restart_engine"
    )
    # FIX-F: the wrapper actually ran, and at start() entry X was ALREADY invalidated.
    assert "status_at_start" in start_entry, "bridge.start() was never invoked by _restart_engine"
    assert start_entry["status_at_start"] is not IdentityStatus.AUTHORITATIVE, (
        "invalidate_descriptor_transport() must run BEFORE bridge.start(): at start() entry "
        f"channel X was {start_entry['status_at_start']!r} (expected already-invalidated). "
        "A mutation moving invalidate after start() would leave X AUTHORITATIVE here."
    )
    # Sanity: the stubbed engine/timer bits were actually exercised by production.
    min_self._stop_engine.assert_called_once()
    min_self._start_engine.assert_called_once()
    min_self._data_timer.stop.assert_called_once()
    min_self._data_timer.start.assert_called_once()
    min_self._health_timer.stop.assert_called_once()
    min_self._health_timer.start.assert_called_once()
    post_restart = w._descriptor_store.identity_status(ch)
    assert post_restart is not IdentityStatus.AUTHORITATIVE, (
        f"After _restart_engine, X must NOT be AUTHORITATIVE (invalidate ran before start); got {post_restart}"
    )
    assert len(dispatch_calls) == 1, f"_restart_engine must not dispatch any reading; got {len(dispatch_calls)}"

    # (e) Re-establish the SUB subscription against the restarted bridge, then a
    # legacy-absent reading on X must NOT restore AUTHORITATIVE.
    _reconnect_sentinel_gate(zmq_harness, timeout_s=20.0)
    r2 = _make_reading(channel=ch, value=2.0)
    zmq_harness.publish(r2, descriptor_envelope=None)
    ql2 = zmq_harness.drain_until(1, timeout_s=15.0)
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql2:
            w.dispatch_qualified_reading(q)
    post_legacy = w._descriptor_store.identity_status(ch)
    assert post_legacy is not IdentityStatus.AUTHORITATIVE, (
        f"Post-restart legacy-absent reading must NOT restore AUTHORITATIVE; got {post_legacy}"
    )
    assert len(dispatch_calls) == 2, f"Post-restart legacy publish must bring total to 2; got {len(dispatch_calls)}"

    # (f) A fresh valid descriptor (revision 2) on X requalifies to AUTHORITATIVE.
    r3 = _make_reading(channel=ch, value=3.0)
    valid_env_v2 = _encode_envelope(r3, revision=2)
    zmq_harness.publish(r3, descriptor_envelope=valid_env_v2)
    ql3 = zmq_harness.drain_until(1, timeout_s=15.0)
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql3:
            w.dispatch_qualified_reading(q)
    assert w._descriptor_store.identity_status(ch) is IdentityStatus.AUTHORITATIVE, (
        "Fresh valid descriptor after _restart_engine must requalify X to AUTHORITATIVE"
    )
    assert len(dispatch_calls) == 3, f"Exactly 3 total dispatches expected; got {len(dispatch_calls)}"
    assert [r.value for r in dispatch_calls] == [1.0, 2.0, 3.0], (
        f"Dispatch order/values must be exactly [1.0, 2.0, 3.0]; got {[r.value for r in dispatch_calls]}"
    )


# ---------------------------------------------------------------------------
# T4 — SHUTDOWN settles cleanly; lifecycle race N≥3 (Codex req 4)
# ---------------------------------------------------------------------------


def _run_one_lifecycle(pub_addr: str, *, iteration: int) -> None:
    """One start/publish/drain/shutdown iteration on a given pub_addr.

    The bridge and publisher are fresh each iteration; the pub_addr is reused
    to prove no endpoint leak between iterations.
    """
    import asyncio
    import threading

    from cryodaq.core.broker import PublishedReading
    from cryodaq.core.zmq_bridge import DEFAULT_TOPIC, ZMQPublisher

    # -- fresh event loop + publisher (mirrors the Phase-1 harness pattern) --
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()), daemon=True)
    t.start()

    queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
    publisher = ZMQPublisher(pub_addr, topic=DEFAULT_TOPIC)
    asyncio.run_coroutine_threadsafe(publisher.start(queue), loop).result(timeout=10.0)

    # -- fresh bridge --
    bridge = ZmqBridge(pub_addr=pub_addr)
    bridge.start()

    # -- sentinel-connect gate (mirrors Phase-1 harness): publish readings in a loop
    # until the SUB socket has connected and at least one arrives.  ZMQ connect() is
    # non-blocking; messages published before subscribe completes are dropped.
    _sentinel_ch = "e2e.p2.t4.sentinel"
    _sentinel_r = _make_reading(channel=_sentinel_ch, value=0.0)
    _connect_deadline = time.monotonic() + 15.0
    _sentinel_arrived = False
    while time.monotonic() < _connect_deadline and not _sentinel_arrived:
        asyncio.run_coroutine_threadsafe(queue.put(_sentinel_r), loop).result(timeout=2.0)
        time.sleep(0.1)
        for qr in bridge.poll_readings_with_descriptor():
            if qr.reading.channel == _sentinel_ch:
                _sentinel_arrived = True
                break
    assert _sentinel_arrived, f"Iteration {iteration}: sentinel never arrived (connect gate)"

    # -- now publish the real test reading --
    ch = f"e2e.p2.t4.iter{iteration}"
    r = _make_reading(channel=ch, value=float(iteration))
    env = _encode_envelope(r)
    item = PublishedReading(reading=r, descriptor_envelope=env)
    asyncio.run_coroutine_threadsafe(queue.put(item), loop).result(timeout=5.0)

    # Drain until 1 reading arrives (bounded deadline, not sole sync primitive)
    accumulated = []
    drain_deadline = time.monotonic() + 10.0
    while time.monotonic() < drain_deadline and len(accumulated) < 1:
        batch = [qr for qr in bridge.poll_readings_with_descriptor() if qr.reading.channel == ch]
        accumulated.extend(batch)
        if not accumulated:
            time.sleep(0.02)

    assert len(accumulated) == 1, f"Iteration {iteration}: expected 1 test reading, got {len(accumulated)}"

    # -- assert no further dispatch after shutdown --
    bridge.shutdown()

    # After shutdown: is_alive must be False
    assert not bridge.is_alive(), f"Iteration {iteration}: bridge must not be alive after shutdown()"
    # is_healthy must be False
    assert not bridge.is_healthy(), f"Iteration {iteration}: is_healthy() must be False after shutdown()"
    # drain returns empty after shutdown
    post_shutdown = bridge.poll_readings_with_descriptor()
    assert post_shutdown == [], (
        f"Iteration {iteration}: poll_readings_with_descriptor must return empty after shutdown; got {post_shutdown}"
    )

    # -- cleanup publisher and loop --
    asyncio.run_coroutine_threadsafe(publisher.stop(), loop).result(timeout=5.0)
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=5.0)


def test_t4_shutdown_settles_no_leak_3x() -> None:
    """Shutdown settles cleanly; endpoint reusable; lifecycle race N=3 iterations.

    Each iteration: start bridge on same pub_addr → publish → drain (exact-once) →
    shutdown → assert is_alive=False, is_healthy=False, empty drain, endpoint reusable.

    T5 regression kill: any lifecycle race or endpoint leak surfaces here.
    """
    import socket as _socket

    pub_addr = allocate_pub_addr()

    # Run 3 full lifecycle iterations on the SAME address
    for i in range(1, 4):
        _run_one_lifecycle(pub_addr, iteration=i)

        # Prove endpoint/port is reusable: bind a plain TCP socket to the same port
        port = int(pub_addr.split(":")[-1])
        try:
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.close()
        except OSError as exc:
            raise AssertionError(
                f"Iteration {i}: port {port} not reusable after shutdown — endpoint leaked: {exc}"
            ) from exc


def test_t4_shutdown_repeat_1(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """Harness-based shutdown: publish, drain, shutdown, assert clean. (repeat 1)"""
    _t4_harness_shutdown_core(zmq_harness, tag="r1")


def test_t4_shutdown_repeat_2(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """Harness-based shutdown: publish, drain, shutdown, assert clean. (repeat 2)"""
    _t4_harness_shutdown_core(zmq_harness, tag="r2")


def test_t4_shutdown_repeat_3(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """Harness-based shutdown: publish, drain, shutdown, assert clean. (repeat 3)"""
    _t4_harness_shutdown_core(zmq_harness, tag="r3")


def _t4_harness_shutdown_core(harness: ZmqHarness, tag: str) -> None:
    """Publish one reading, drain, call teardown (shutdown), assert post-shutdown state."""
    ch = f"e2e.p2.t4.{tag}"
    r = _make_reading(channel=ch, value=42.0)
    valid_env = _encode_envelope(r)

    harness.publish(r, descriptor_envelope=valid_env)
    ql = harness.drain_until(1, timeout_s=15.0)
    assert len(ql) == 1, f"T4 {tag}: expected 1 reading, got {len(ql)}"

    _app()
    w, dispatch_calls = _recording_window()
    with patch.object(w, "_dispatch_reading", side_effect=dispatch_calls.append):
        for q in ql:
            w.dispatch_qualified_reading(q)

    assert len(dispatch_calls) == 1, f"T4 {tag}: exact-once before shutdown"

    # Explicit bridge shutdown (harness teardown also does this, but we verify before teardown)
    harness.bridge.shutdown()

    # After shutdown: no further readings
    post = harness.bridge.poll_readings_with_descriptor()
    assert post == [], f"T4 {tag}: empty drain after shutdown; got {post}"
    assert not harness.bridge.is_alive(), f"T4 {tag}: bridge must not be alive after shutdown"
    assert not harness.bridge.is_healthy(), f"T4 {tag}: is_healthy must be False after shutdown"


# ---------------------------------------------------------------------------
# T5 — REGRESSION-FAIL GUARDRAILS summary (all folded into T1–T4)
# ---------------------------------------------------------------------------
# The following regression classes are killed by the tests above:
#
#  Regression: poll_readings() drain
#    → test_t2_static_no_poll_readings_in_app_py
#    → test_t2_static_no_poll_readings_in_launcher_py
#
#  Regression: double-dispatch
#    → test_t1_mixed_batch_exact_once_no_invented_identity (len(dispatch_calls) == total)
#    → test_t4_shutdown_repeat_{1,2,3} (exact-once before shutdown)
#
#  Regression: skipped invalidation
#    → test_t3_behavioural_invalidate_then_requalify (post-invalidate REFUSED)
#    → test_t3_static_all_five_invalidate_before_start (ordering in source)
#    → test_t3_real_socket_invalidate_requalify_via_bridge (real socket)
#
#  Regression: bypassed store
#    → test_t1_mixed_batch_exact_once_no_invented_identity (identity_status checks)
#    → test_t3_* (REFUSED/AUTHORITATIVE store checks)
#
#  Regression: invented identity (non-authoritative → AUTHORITATIVE)
#    → test_t1_mixed_batch_exact_once_no_invented_identity (REFUSED assert on malformed)
#    → _run_t1_core (REFUSED assert on corrupt envelope)
