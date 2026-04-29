Verdict: PASS

Minor improvement suggestions:

1. **The async test could assert no direct hardware write occurred.** The expanded docstring emphasizes that `update_target` intentionally avoids direct SCPI writes, yet the test only verifies the in-memory update. Adding something like `k.write.assert_not_called()` (or whichever method issues SCPI commands) would directly validate the stated design intent and catch regressions if a future refactor adds a direct write.

2. **Missing negative test for config-limit validation.** The original docstring mentions "Validates against config limits," but no test covers the rejection path (e.g., setting p_target above the allowed maximum). A test asserting `result["ok"] is False` and `runtime.p_target` unchanged would close that gap.

3. **The `_SLOW_COMMANDS` additions could reference a rationale for the 30s value.** The comment explains *why* these commands need a longer envelope, but not *why* 30 s is sufficient. A brief note (e.g., "30 s covers worst-case USBTMC reset seen in CI log #1234") would make the threshold auditable and prevent someone from accidentally lowering it.
