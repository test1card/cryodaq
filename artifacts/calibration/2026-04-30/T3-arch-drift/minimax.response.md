Verdict: CONSISTENT  

The test validates that `update_target()` writes the new power target to `runtime.p_target` immediately, matching the docstring’s promise that the hardware voltage is updated in the next poll cycle by the regulation loop.
