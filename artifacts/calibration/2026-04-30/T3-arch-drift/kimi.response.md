 Verdict: DRIFT

- `safety_manager.py` (`update_target` docstring): States the instrument output "converges within one poll interval (typically ≤1 s)". This contradicts `keithley_2604b.py` (`read_channels` loop), where `MAX_DELTA_V_PER_STEP = 0.5` caps the voltage change per poll cycle; any required jump larger than 0.5 V takes multiple cycles to reach the target.
- `tests/core/test_safety_manager.py` (test docstring): Claims "hardware voltage converges on the next poll cycle", which is inconsistent with the same slew-rate limiter in the regulation loop.
- `tests/core/test_safety_manager.py` (test body): Only verifies the in-memory assignment (`runtime.p_target == 0.5`). It does not assert that `update_target` avoids direct SCPI writes, nor does it exercise or verify the hardware convergence behavior described in the docstrings.
