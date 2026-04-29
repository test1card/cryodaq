# Code Review

Review the following diff. Find any issues.
If the diff is correct as-is, say PASS.

## Diff (commit 189c4b7)

```
diff --git a/src/cryodaq/core/safety_manager.py b/src/cryodaq/core/safety_manager.py
--- a/src/cryodaq/core/safety_manager.py
+++ b/src/cryodaq/core/safety_manager.py
@@ -431,1 +431,11 @@ class SafetyManager:
-        """Live-update P_target on an active channel. Validates against config limits."""
+        """Live-update P_target on an active channel. Validates against config limits.
+
+        Updates ``runtime.p_target`` in-memory. The hardware voltage is NOT changed
+        here directly — the P=const regulation loop in
+        ``Keithley2604B.read_channels()`` reads ``runtime.p_target`` on every poll
+        cycle and recomputes ``target_v = sqrt(p_target * R)``, so the instrument
+        output converges within one poll interval (typically ≤1 s).
+
+        This is intentional: slew-rate limiting and compliance checks live in the
+        regulation loop and must not be bypassed by direct SCPI writes here.
+        """

diff --git a/src/cryodaq/core/zmq_bridge.py b/src/cryodaq/core/zmq_bridge.py
--- a/src/cryodaq/core/zmq_bridge.py
+++ b/src/cryodaq/core/zmq_bridge.py
@@ -55,0 +55,4 @@
+        # Safety commands that drive USBTMC hardware — must not be cancelled
+        # by the fast 2-second envelope during a slow USB transaction.
+        "keithley_emergency_off",
+        "keithley_stop",

+def test_slow_commands_covers_safety_critical_hardware_ops() -> None:
+    """HF2 — keithley_emergency_off and keithley_stop must use the 30 s envelope."""
+    assert "keithley_emergency_off" in _SLOW_COMMANDS
+    assert "keithley_stop" in _SLOW_COMMANDS
+    assert _timeout_for({"cmd": "keithley_emergency_off"}) == HANDLER_TIMEOUT_SLOW_S
+    assert _timeout_for({"cmd": "keithley_stop"}) == HANDLER_TIMEOUT_SLOW_S

+async def test_update_target_updates_runtime_p_target_immediately():
+    """HF1 — update_target() is a delayed-update, not a hardware no-op."""
+    k = _mock_keithley()
+    runtime = MagicMock()
+    runtime.active = True
+    runtime.p_target = 0.1
+    k._channels = {"smua": runtime}
+    mgr, _ = await _make_manager(keithley=k, mock=True)
+    mgr._keithley = k
+    mgr._state = SafetyState.RUNNING
+    mgr._active_sources = {"smua"}
+    result = await mgr.update_target(0.5, channel="smua")
+    assert result["ok"] is True
+    assert result["p_target"] == 0.5
+    assert runtime.p_target == 0.5
+    await mgr.stop()
```

## Output format
- Verdict: PASS or FAIL
- If FAIL: list issues with severity (CRITICAL/HIGH/MEDIUM/LOW) + explanation
- If PASS: optional minor improvement suggestions (max 3, genuine only)

Hard cap 1000 words. No preamble.
