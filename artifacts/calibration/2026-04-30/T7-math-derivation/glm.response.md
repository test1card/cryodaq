## 1. Formula for u(G)

Using the Guide to Uncertainty in Measurement (GUM) framework for uncorrelated inputs, the combined standard uncertainty in the thermal conductance, u(G), is:

u(G) = sqrt( [1 / (DeltaT - DeltaT0)]^2 * u(P)^2 + [P / (DeltaT - DeltaT0)^2]^2 * u(DeltaT)^2 + [P / (DeltaT - DeltaT0)^2]^2 * u(DeltaT0)^2 )

Or, factored more cleanly:

u(G) = sqrt( u(P)^2 / (DeltaT - DeltaT0)^2 + P^2 / (DeltaT - DeltaT0)^4 * [u(DeltaT)^2 + u(DeltaT0)^2] )

## 2. Step-by-Step Derivation

According to the GUM, for a function y = f(x1, x2, ..., xn), the combined standard uncertainty u(y) is found using the Law of Propagation of Uncertainty. Assuming the input quantities are uncorrelated (covariance terms are zero), the general formula is:

u(y)^2 = Sum_i [ (df/dx_i)^2 * u(x_i)^2 ]

Our function is G = f(P, DeltaT, DeltaT0) = P / (DeltaT - DeltaT0).

To simplify the notation, let D = DeltaT - DeltaT0, which represents the true temperature difference across the sample due to the applied power. Therefore, G = P / D.

**Step 1: Calculate the partial derivatives (sensitivity coefficients)**

a) Partial derivative with respect to P:
dG/dP = 1 / D
dG/dP = 1 / (DeltaT - DeltaT0)

b) Partial derivative with respect to DeltaT:
dG/dDeltaT = d/dDeltaT [ P * (DeltaT - DeltaT0)^-1 ]
dG/dDeltaT = -P * (DeltaT - DeltaT0)^-2 * 1
dG/dDeltaT = -P / (DeltaT - DeltaT0)^2

c) Partial derivative with respect to DeltaT0:
dG/dDeltaT0 = d/dDeltaT0 [ P * (DeltaT - DeltaT0)^-1 ]
dG/dDeltaT0 = -P * (DeltaT - DeltaT0)^-2 * (-1)
dG/dDeltaT0 = P / (DeltaT - DeltaT0)^2

**Step 2: Square the partial derivatives and multiply by the squared input uncertainties**

Term 1 (Power): (dG/dP)^2 * u(P)^2 = [1 / (DeltaT - DeltaT0)^2] * u(P)^2

Term 2 (DeltaT): (dG/dDeltaT)^2 * u(DeltaT)^2 = [P^2 / (DeltaT - DeltaT0)^4] * u(DeltaT)^2

Term 3 (DeltaT0): (dG/dDeltaT0)^2 * u(DeltaT0)^2 = [P^2 / (DeltaT - DeltaT0)^4] * u(DeltaT0)^2

**Step 3: Sum the terms and take the square root**

u(G)^2 = Term 1 + Term 2 + Term 3

u(G)^2 = [1 / (DeltaT - DeltaT0)^2] * u(P)^2 + [P^2 / (DeltaT - DeltaT0)^4] * u(DeltaT)^2 + [P^2 / (DeltaT - DeltaT0)^4] * u(DeltaT0)^2

u(G) = sqrt( u(P)^2 / (DeltaT - DeltaT0)^2 + P^2 * [u(DeltaT)^2 + u(DeltaT0)^2] / (DeltaT - DeltaT0)^4 )

This matches the formula stated in Section 1.

## 3. Relative Uncertainty

The relative uncertainty is calculated as u(G)/|G|. First, we need to express G^2:

G^2 = P^2 / (DeltaT - DeltaT0)^2

Now, divide the absolute uncertainty squared, u(G)^2, by G^2:

[u(G)/|G|]^2 = u(G)^2 / G^2

= { u(P)^2 / (DeltaT - DeltaT0)^2 + P^2 * [u(DeltaT)^2 + u(DeltaT0)^2] / (DeltaT - DeltaT0)^4 } / { P^2 / (DeltaT - DeltaT0)^2 }

We can split this into three fractions:

1.  [ u(P)^2 / (DeltaT - DeltaT0)^2 ] / [ P^2 / (DeltaT - DeltaT0)^2 ] = u(P)^2 / P^2
2.  [ P^2 * u(DeltaT)^2 / (DeltaT - DeltaT0)^4 ] / [ P^2 / (DeltaT - DeltaT0)^2 ] = u(DeltaT)^2 / (DeltaT - DeltaT0)^2
3.  [ P^2 * u(DeltaT0)^2 / (DeltaT - DeltaT0)^4 ] / [ P^2 / (DeltaT - DeltaT0)^2 ] = u(DeltaT0)^2 / (DeltaT - DeltaT0)^2

Summing these terms and taking the square root gives the relative uncertainty:

u(G)/|G| = sqrt( [u(P)/P]^2 + [u(DeltaT)/(DeltaT - DeltaT0)]^2 + [u(DeltaT0)/(DeltaT - DeltaT0)]^2 )

This form clearly shows that the relative uncertainty in G is the root-sum-of-squares of the relative uncertainty in the power and the relative uncertainties of the temperature differences normalized by the *effective* temperature difference (DeltaT - DeltaT0), rather than the absolute temperature differences.

## 4. Edge Cases

**When DeltaT - DeltaT0 approaches zero:**
As the effective temperature difference (DeltaT - DeltaT0) approaches zero, both the absolute uncertainty u(G) and the relative uncertainty u(G)/|G| approach infinity. Physically, this occurs when the applied power is too small to generate a measurable temperature gradient above the baseline offset. Mathematically, the sensitivity coefficients for DeltaT and DeltaT0 (-P/D^2 and P/D^2) diverge, meaning infinitesimal changes in the temperature readings result in arbitrarily large swings in the calculated conductance. In practice, measurements in this regime are completely dominated by noise, rendering the calculated G meaningless.

**When P approaches zero:**
If the heater power P approaches zero while DeltaT - DeltaT0 remains non-zero (e.g., due to parasitic heat loads), the absolute uncertainty u(G) approaches zero because the uncertainty in the temperature terms is multiplied by P. However, the *relative* uncertainty u(G)/|G| will still diverge because the term u(P)/P approaches infinity. A small absolute power uncertainty constitutes a massive relative uncertainty at near-zero power.

## 5. Optional: Independence Assumption in Cryogenic Experiments

The assumption that DeltaT and DeltaT0 are uncorrelated is often unrealistic in cryogenic experiments. 

DeltaT is the measured temperature difference at operating power, and DeltaT0 is the baseline temperature difference at zero power. Both are typically measured using the exact same pair of thermometers (e.g., a hot sensor and a cold sensor). 

If the thermometers have a systematic calibration offset that does not change with temperature, this offset will be present in both DeltaT and DeltaT0, meaning their errors are highly correlated. The GUM framework accounts for correlated inputs by adding covariance terms:

u(G)^2 = Sum_i [ (dG/dx_i)^2 * u(x_i)^2 ] + 2 * Sum_i<j [ (dG/dx_i) * (dG/dx_j) * u(x_i, x_j) ]

For DeltaT and DeltaT0, the covariance term is:

2 * (dG/dDeltaT) * (dG/dDeltaT0) * u(DeltaT, DeltaT0)
= 2 * [ -P / (DeltaT - DeltaT0)^2 ] * [ P / (DeltaT - DeltaT0)^2 ] * u(DeltaT, DeltaT0)
= -2 * P^2 / (DeltaT - DeltaT0)^4 * u(DeltaT, DeltaT0)

Because the product of the two partial derivatives is negative, a positive covariance u(DeltaT, DeltaT0) (which occurs when the errors move in the same direction) actually *reduces* the total uncertainty u(G). 

This makes intuitive sense: if a calibration offset causes both DeltaT and DeltaT0 to be overestimated by the same amount, that error cancels out when you calculate the effective temperature difference (DeltaT - DeltaT0). By ignoring the correlation and assuming independence, we are likely overestimating the uncertainty in G. However, if the thermometer calibrations shift non-linearly between the P=0 and P>0 states (common in cryogenic sensors like Cernox or RuO2 over large temperature sweeps), the errors may only partially cancel, complicating the covariance estimation.
