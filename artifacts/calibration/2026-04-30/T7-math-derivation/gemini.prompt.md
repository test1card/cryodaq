# Uncertainty Propagation Derivation

Derive the propagation of measurement uncertainties for the thermal conductance formula:

    G = P / (ΔT - ΔT₀)

where P is heater power, ΔT is the measured temperature difference across the sample,
and ΔT₀ is a calibration offset (baseline temperature difference with zero power).

Each input has its own standard uncertainty:
- u(P) for power
- u(ΔT) for temperature difference
- u(ΔT₀) for calibration offset

Assume the inputs are uncorrelated (independent measurements).

## Output format

1. State the formula for u(G) in terms of input uncertainties
2. Show the derivation step-by-step using GUM (Guide to Uncertainty in Measurement)
   methodology — specifically using partial derivatives to propagate uncertainties
3. Express the result as relative uncertainty u(G)/|G|
4. Note any edge cases (e.g., what happens when ΔT - ΔT₀ approaches zero)
5. Optional: discuss whether the independence assumption is realistic in a cryogenic
   experiment where ΔT and ΔT₀ may share a common reference sensor

Hard cap 2000 words. Plain text math notation is fine (use ^2, sqrt(), etc.).
Show all derivation steps — do not skip to the answer.
