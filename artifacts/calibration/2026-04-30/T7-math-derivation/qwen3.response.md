We are given the thermal conductance formula:

\[
G = \frac{P}{\Delta T - \Delta T_0}
\]

with input quantities:
- \(P\): heater power (W)
- \(\Delta T\): measured temperature difference across the sample (K)
- \(\Delta T_0\): calibration offset (baseline ΔT at zero power) (K)

Respective **standard uncertainties** (1σ):
- \(u(P)\): standard uncertainty in power
- \(u(\Delta T)\): standard uncertainty in ΔT
- \(u(\Delta T_0)\): standard uncertainty in Δ₀

Assume **uncorrelated inputs** (independent measurement errors), i.e., covariance terms vanish.

We are to derive the **standard uncertainty in G**, \(u(G)\), using the **GUM (JCGM 100:2008)** methodology.

---

### Step 1: General Uncertainty Propagation Formula (GUM Eq. 10)

For a function \(y = f(x_1, x_2, ..., x_n)\) of \(n\) input quantities \(x_i\) with estimates \(\hat{x}_i\), and assuming linear approximation, the **standard uncertainty** in \(y\) is:

\[
u^2(y) = \sum_{i=1}^n \left( \frac{\partial f}{\partial x_i} \right)^2 u^2(x_i)
\]

**No covariance terms** appear when the inputs are uncorrelated.

In our case, define:

\[
G = f(P, \Delta T, \Delta T_0) = \frac{P}{\Delta T - \Delta T_0}
\]

Let us denote the denominator as:

\[
D = \Delta T - \Delta T_0
\]

so \(G = P / D\). Then:

\[
\frac{\partial G}{\partial P} = \frac{1}{D}, \quad
\frac{\partial G}{\partial (\Delta T)} = -\frac{P}{D^2}, \quad
\frac{\partial G}{\partial (\Delta T_0)} = +\frac{C?}
\]

Wait: carefully differentiate \(G = P \cdot D^{-1}\), and note that:

\[
D = \Delta T - \Delta T_0 \implies \frac{\partial D}{\partial (\Delta T)} = 1, \quad \frac{\partial D}{\partial (\Delta T_0)} = -1
\]

So by product rule:

\[
\frac{\partial G}{\partial (\Delta T)} = P \cdot (-1) \cdot D^{-2} \cdot \frac{\partial D}{\partial (\Delta T)} = -\frac{P}{D^2} \cdot 1 = -\frac{P}{D^2}
\]

Similarly:

\[
\frac{\partial G}{\partial (\Delta T_0)} = P \cdot (-1) \cdot D^{-2} \cdot \frac{\partial D}{\partial (\Delta T_0)} = -\frac{D}{P} \cdot (-1) \cdot P \cdot D^{-2}
\]

Better to compute directly:

\[
G = \frac{P}{\Delta T - \Delta_0} = \frac{P}{\Delta T - \Delta T_0}
\]

Treat numerator and denominator both dependent on ΔT and ΔT₀:

But more systematically:

Let \(x = P\), \(y = \Delta T\), \(z = \Delta T_0\), so:

\[
G = \frac{x}{y - z}
\]

Partial derivatives:

\[
\frac{\partial G}{\partial x} = \frac{1}{y - z}
\]

\[
\frac{\partial G}{\partial y} = x \cdot (-1) \cdot (y - z)^{-2} \cdot \frac{\partial (y - z)}{\partial y} = -\frac{x}{(y - z)^2} \cdot (1) = -\frac{x}{(y - z)^2}
\]

\[
\frac{\partial G}{\partial z} = x \cdot (-1) \cdot (y - z)^{-2} \cdot \frac{\partial (y - z)}{\partial z} = -\frac{x}{(y - z)^2} \cdot (-1) = +\frac{x}{(y - z)^2}
\]

So indeed:

\[
\frac{\partial G}{\partial P} = \frac{1}{\Delta T - \Delta T_0}
\]

\[
\frac{\partial G}{\partial (\Delta T)} = -\frac{P}{(\Delta T - \Delta T_0)^2}
\]

\[
\frac{\partial G}{\partial (\Delta T_0)} = +\frac{P}{(\Delta T - \Delta T_0)^2}
\]

Check: Since denominator = ΔT − ΔT₀, ∂denom/∂(ΔT) = 1, ∂denom/∂(ΔT₀) = −1.

Now apply uncertainty propagation:

\[
u^2(G) = \left( \frac{\partial G}{\partial P} \right)^2 u^2(P) + \left( \frac{\partial G}{\partial (\Delta T)} \right)^2 u^2(\Delta T) + \left( \frac{\partial G}{\partial (\Delta T_0)} \right)^2 u^2(\Delta T_0)
\]

Substitute the derivatives:

\[
u^2(G) = \left( \frac{1}{\Delta T - \Delta T_0} \right)^2 u^2(P) + \left( -\frac{P}{(\Delta T - \Delta T_0)^2} \right)^2 u^2(\Delta T) + \left( \frac{P}{(\Delta T - \Delta T_0)^2} \Delta T_0 \right)^2 u^2(\Delta T_0)
\]

Careful: in the second and third terms, we square the derivative:

- \(\left( -\frac{P}{(\Delta T - \Delta T_0)^2} \right)^2 = \frac{P^2}{(\Delta T - \Delta T_0)^4}\)
- Same for derivative w.r.t ΔT₀: derivative = +P/(ΔT − ΔT₀)², so squared same: \(P^2 / (\Delta T - ΔT₀)^4\)

So both have identical coefficients.

Thus:

\[
u^2(G) = \frac{1}{(\Delta T - \Delta T_0)^2} u^2(P) + \frac{P^2}{(\Delta T - \Delta T_0)^4} u^2(\Delta T) + \frac{P^2}{(\Delta T - \Delta T_0)^4} u^2(\Delta T_0)
\]

We can factor common denominator:

\[
u^2(G) = \frac{1}{(\Delta T - \Delta T_0)^2} u^2(P) + \frac{P^2}{(\Delta T - \Delta T_0)^4} \left[ u^2(\Delta T) + u^2(\Delta T_0) \right]
\]

But wait: there is a sign issue: derivative w.r.t ΔT is negative, but when squared, sign disappears.

So:

\[
u^2(G) = \frac{u^2(P)}{(\Delta T - \Delta T_0)^2} + \frac{P^2}{(\Delta T - \Delta T_0)^4} \left[ u^2(\Delta T) + u^2(\Delta T_0) \right]
\]

But note the derivative w.r.t ΔT gives \(-P/(\Delta T - ΔT_0)^2\); derivative w.r.t ΔT₀ gives \(+P/(\Delta T - ΔT_0)^2\); same magnitude.

Thus:

\[
u^2(G) = \frac{1}{(\Delta T - \Delta T_0)^2} u^2(P) + \frac{P^2}{(\Delta T - ΔT_0)^4} \left[ u^2(\Delta T) + u^2(\Delta T_0) \right]
\]

But check: derivative w.r.t ΔT: \(-P/(ΔT - ΔT_0)^2\), square gives \(P^2/(ΔT - ΔT_0)^4\).

Derivative w.r.t ΔT₀: \(+P/(ΔT - ΔT_0)^2\), square same: \(P^2/(ΔT - ΔT_0)^4\).

Hence both terms add identically.

So final exact expression:

\[
u^2(G) = \frac{u^2(P)}{(\Delta T - \Delta T_0)^2} + \frac{P^2}{(\Delta T - \Delta T_0)^4} \left[u^2(\Delta T) + u^2(\Delta T_0)\right]
\]

We can factor further:

\[
u^2(G) = \frac{1}{(\Delta T - \Delta T_0)^2} u^2(P) + \frac{P^2}{(\Delta T - \Delta T_0)^4} \left[ u^2(\Delta T) + u^2(\Delta_0) \right]
\]

Alternatively write in terms of denominator D = ΔT − ΔT₀:

\[
u^2(G) = \frac{1}{D^2} u^2(P) + \frac{P^2}{D^4} \left[ u^2(\Delta T) + u^2(\Delta T_0) \right]
\]

Alternatively, combine into single fraction:

\[
u^2(G) = \frac{D^2 u^2(P) + P^2 [ u^2(\Delta T) + u^2(\Delta T_0) ] }{D^4}
\]

Check:

Numerator: first term: \(D^2 u^2(P)\) (since \(1/D^2 \to D^2/D^4\)). Indeed:

\[
\frac{u^2(P)}{D^2} = \frac{D^2 u^2(P)}{D^4}\)

Second term: \(\frac{P^2}{D^4} [ u^2(\Delta T) + u^2(\Delta T_0) ]\).

Thus:

\[
u^2(G) = \frac{ D^2 u^2(P) + P^2 (u^2(\Delta T) + u^2(\Delta T_0))}{D^4}
\]

So final compact:

\[
u^2(G) = \frac{1}{(\Delta T - \Delta T_0)^4} \left[ (\Delta T - \Delta T_0)^2 u^2(P) + P^2 \left(u^2(\Delta T) + u^2(\Delta T_0) \right) \right]
\]

Thus:

\[
u(G) = \frac{1}{(\Delta T - \Delta T_0)^2} \sqrt{ u^2(P) + \left( \frac{P}{(\Delta T - \Delta T_0)^2} \right)^2 \left[ u^2(\Delta T) + u^2(\Delta T_0) \right] }
\]

But better to leave as squared.

Now express **relative uncertainty**:

\[
\frac{u(G)}{|G|} = \frac{u(G)}{|P| / |(\Delta T - \Delta T_0)|} = \frac{u(G) (\Delta T - \Delta T_0)}{P}
\]

Let’s compute:

\[
\frac{u(G)}{|G|} = \frac{ (\Delta T - \Delta_0) }{P} \cdot u(G)
\]

But we have u(G) from above.

Let D = ΔT − ΔT₀.

From:

\[
u^2(G) = \frac{1}{D^2} u^2(P) + \frac{P^2}{D^4} (u^2(\Delta T) + u^2(\Delta_0))
\]

Then:

\[
\left( \frac{u(G)}{G} \right)^2 = \left( \frac{u(G)}{P/D} \right)^2 = \left( \frac{u(G) D}{P} \right)^2 = \frac{D^2}{P^2} u^2(G)
\]

So compute:

\[
\left( \frac{u(G)}{G} \right)^2 = \frac{D^2}{P^2} \left[ \frac{u^2(P)}{D^2} + \frac{P^2}{D^4} (u^2(\Delta T) + u^2(\Delta_0)) \right] = \frac{u^2(P)}{P^2} + \frac{u^2(\Delta T) + u^2(\Delta_0)}{D^2}
\]

Thus:

\[
\frac{u(G)}{|G|} = \sqrt{ \left( \frac{u(P)}{P} \right)^2 + \frac{u^2(\Delta T) + u^2(\Delta T_0)}{(\Delta T - \Delta T_0)^2}
\]

But careful: the denominator in the second term: D^2 = (ΔT − ΔT₀)^2, so:

\[
\boxed{ \frac{u(G)}{|G|} = \sqrt{ \left( \frac{u(P)}{P} \right)^2 + \frac{u^2(\Delta T) + u^2(\Delta T_0)}{(\Delta T - \Delta T_0)^2} }
\]

Wait, units check: u(P)/P is dimensionless. u(ΔT) and u(ΔT₀) have units K, D^2 has K², so ratio dimensionless. Good.

Alternatively write as:

\[
\frac{u(G)}{|G|} = \sqrt{ \left( \frac{u(P)}{P} \right)^2 + \left( \frac{u_{\Delta T}}{(\Delta T - \Delta_0)} \right)^2 + \left( \frac{u_{\Delta_0}}{(\Delta T - \Delta_0)} \right)^2}
\]

But note that derivative w.r.t ΔT and ΔT₀ contribute same, so can combine into effective denominator.

Thus final relative uncertainty:

\[
\frac{u(G)}{|G|} = \sqrt{ \left( \frac{u(P)}{P} \right)^2 + \frac{u^2(\Delta T) + u^2(\Delta T_0)}{(\Delta T - \Delta T_0)^2}
\]

This is the GUM result.

Now discuss **edge cases**:

If denominator \(ΔT - ΔT_0 \to 0\), then \(G \to \pm \infty\). physically unrealistic because no heat flows at zero ΔT, but mathematically diverges. In propagation formula, denominators contain powers of \(ΔT - ΔT_0\), so uncertainty blows up dramatically: the relative uncertainty term \(\propto 1 / (ΔT - ΔT_0)^2\) diverges, indicating large sensitivity. So measurement design should ensure \(|ΔT - ΔT_0|\) is well above noise floor.

Also, if \(ΔT\) and \(ΔT_0\) share common sensor (e.g., both measured with same thermometer), then ΔT and ΔT₀ are **correlated**, covariance term appears in full GUM formula.

Full covariance-included formula:

\[
u^2(G) = \left( \frac{\partial G}{\partial (\Delta T)} \right)^2 u^2(\Delta T) + \left( \frac{\partial G}{\partial (\Delta T_0)} \right)^2 u^2(\Delta T_0) + 2 \frac{\partial G}{\partial (\Delta T)} \frac{\partial G}{\partial (\Delta T_0)} \operatorname{cov}(\Delta T,\Delta T_0)
\]

where \(\operatorname{cov}(\Delta T,\Delta T_0) = \rho \, u(\Delta T) u(\Delta T_0)\) with correlation coefficient ρ.

In our derivation we set cov=0.

But in cryogenic experiment, ΔT and ΔT₀ might be measured with same temperature sensor, so correlated. This correlation reduces effective uncertainty. For instance, if ΔT and ΔT₀ have correlation ρ, the combined denominator uncertainty becomes:

\[
u^2(\Delta T - \Delta T_0) = u^2(\Delta T) + u^2(\Delta T_0) - 2\rho u(\Delta T) u(\Delta T_0)
\)

So if ρ≈1 (perfect correlation), the variance in the difference can be reduced significantly (e.g., for ρ=1, variance = (u(ΔT) - u(ΔT_0))^2\). If both have same uncertainty σ, variance = 2σ² - 2σ² = 0 in limit ΔT=ΔT₀, meaning exact cancellation.

But physically, ΔT₀ is a *baseline offset*, often measured separately with same sensor and often correlated.

Thus the independence assumption is often not realistic in cryogenic experiments; covariance should be included.

Thus the derived expression is correct under the assumption of independence.

Now write final answer in requested format.

**Answer:**

1. **Formula for u(G):**

\[
u(G) = \frac{1}{|\Delta T - \Delta_0|}\,\sqrt{u^2(P)\;+\;\left[\frac{u(\Delta T)+u(\Delta_0)}{|\Delta T-\Delta_0|}\right]^2}
\]

or more cleanly as squared:

\[
u^2(G) = \frac{1}{(\Delta T - \Delta T_0)^2}\,u^2(P) \;+\;\frac{P^2}{(\Delta T - T_0)^4}\,[\,u^2(\Delta T)+u^2(\Delta_0)\,].
\]

2. **Step-by-step GUM derivation:**

- Express the model: \(G = f(P,\Delta T,\Delta T_0) = P/(ΔT - ΔT_0)\).

- Compute the partial derivatives (GUM Eq. 10):

\[
\frac{\partial G}{\partial P} = \frac{1}{\Delta T - \Delta T_0},
\quad
\frac{\partial G}{\partial (\Delta T)} = -\frac{P}{(\Delta T - \Delta T_0)^2},
\quad
\frac{\partial G}{\partial (\Delta T_0)} = \frac{P}{(\Delta T - \Delta_0)^2}.
\]

- Apply the law of propagation of uncertainty (uncorrelated inputs, zero covariance):

\[
u^2(G) = \left(\frac{\partial G}{\partial P}\right)^2 u^2(P) + \left(\frac{\partial G}{\partial (\Delta T)}\right)^2 u^2(\Delta T) + \left(\frac{\partial G}{\partial (\Delta T_0)}\right)^2 u^2(\Delta_0).
\]

- Substitute the derivatives:

\[
u^2(G) = \frac{1}{(\Delta T - Δ_0)^2} u^2(P) + \frac{P^2}{(\Delta T - Δ_0)^4} u^2(\Delta T) + \frac{P^2}{(\Delta_0)^4} u^2(\Delta_0).
\]

- Combine the temperature terms (both have same coefficient):

\[
u^2(G) = \frac{1}{(\Delta T - Δ_0)^2} u^2(P) + \frac{P^2}{(\Delta T - Δ_0)^4} \left[ u^2(\Delta T) + u^2(\Δ_0)\right].
\]

or, over a common denominator:

\[
u^2(G) = \frac{(\Delta T - Δ_0)^2 u^2(P) + P^2 \left[ u^2(\Δ T) + u^2(\Δ_0) \right] }{(\Delta T - Δ_0)^4}.
\]

3. **Relative uncertainty:

\[
\frac{u(G)}{|G|} = \sqrt{ \left(\frac{u(P)}{P}\right)^2 + \frac{u^2(\Δ T) + u^2(\Δ_0)}{(\Δ T - Δ_0)^2}.
\]

4. **Edge case: when \(Δ T - Δ_0 → 0\):

- The conductance diverges: \(G = P/(Δ T - Δ_0) → ±∞\).

- The uncertainty terms all contain powers of \((Δ T - Δ_0)\) in denominators, so both the estimate and the uncertainty blow up.

- Practically, measurements must be made where the temperature difference significantly exceeds the baseline offset to avoid excessive relative uncertainty.

5. **Comment on independence assumption:

In a cryogenic experiment, \(ΔT\) and \(ΔT_0\) may be measured with the *same* temperature sensor (e.g., a calibrated RuO₂ thermometer or a Si diode). Consequently the measurement errors in both are partially correlated. If a sensor drifts, it shifts both readings equally. In the GUM, this correlation contributes a covariance term:

\[
u^2(G) = \dots + 2\frac{P^2}{(\Delta T - Δ_0)^4} \big[ u^2(ΔT) + u^2(Δ_0) - 2\rho u(ΔT)u(Δ_0) \big].
\]

When \(ρ ≈ 1\), the effective uncertainty in the difference \(ΔT - Δ_0\) can be much smaller than the individual uncertainties. Therefore, the independence assumption often *overestimates the uncertainty in G. A more realistic analysis would estimate the correlation coefficient (e.g., from repeated calibration runs) and include the covariance term, which reduces the overall uncertainty.

**End of derivation.**
