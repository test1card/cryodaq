**1.  Formula for the standard uncertainty of G**

For  

\[
G=\frac{P}{\Delta T-\Delta T_{0}}
\]

the combined standard uncertainty (assuming independent input quantities) is  

\[
\boxed{
u(G)=
\sqrt{
\Bigl(\frac{\partial G}{\partial P}\Bigr)^{2}u^{2}(P)+
\Bigl(\frac{\partial G}{\partial\Delta T}\Bigr)^{2}u^{2}(\Delta T)+
\Bigl(\frac{\partial G}{\partial\Delta T_{0}}\Bigr)^{2}u^{2}(\Delta T_{0})
}
}
\tag{1}
\]

After inserting the partial‑derivative expressions (see step 2) this can be written in a more compact form

\[
\boxed{
u(G)=|G|
\sqrt{
\Bigl(\frac{u(P)}{P}\Bigr)^{2}
+\Bigl(\frac{u(\Delta T)}{\Delta T-\Delta T_{0}}\Bigr)^{2}
+\Bigl(\frac{u(\Delta T_{0})}{\Delta T-\Delta T_{0}}\Bigr)^{2}
}
}
\tag{2}
\]

or, using the variance of the denominator  

\[
D\equiv\Delta T-\Delta T_{0},
\]

\[
u(G)=|G|
\sqrt{
\Bigl(\frac{u(P)}{P}\Bigr)^{2}
+\frac{u^{2}(\Delta T)+u^{2}(\Delta T_{0})}{D^{2}}
}.
\tag{3}
\]

---

**2.  Step‑by‑step GUM derivation (partial‑derivative method)**  

The *Guide to the Expression of Uncertainty in Measurement* (GUM) states that for a quantity \(Y=f(X_{1},X_{2},\dots )\) the variance of \(Y\) is  

\[
u^{2}(Y)=\sum_{i}\Bigl(\frac{\partial f}{\partial X_{i}}\Bigr)^{2}u^{2}(X_{i})
\quad\text{(input quantities are uncorrelated).}
\]

Here the model is  

\[
G=f(P,\Delta T,\Delta T_{0})=\frac{P}{\Delta T-\Delta T_{0}}.
\]

---

**2.1  Partial derivatives**

\[
\frac{\partial G}{\partial P}= \frac{1}{\Delta T-\Delta T_{0}}
      =\frac{G}{P},
\]

\[
\frac{\partial G}{\partial\Delta T}
      =-\frac{P}{(\Delta T-\Delta T_{0})^{2}}
      =-\frac{G}{\Delta T-\Delta T_{0}},
\]

\[
\frac{\partial G}{\partial\Delta T_{0}}
      =+\frac{P}{(\Delta T-\Delta T_{0})^{2}}
      =+\frac{G}{\Delta T-\Delta T_{0}}.
\]

(Notice that the derivatives with respect to \(\Delta T\) and \(\Delta T_{0}\) have opposite sign but the same magnitude.)

---

**2.2  Insert into the variance formula**

\[
\begin{aligned}
u^{2}(G)&=
\Bigl(\frac{1}{\Delta T-\Delta T_{0}}\Bigr)^{2}u^{2}(P)\\[4pt]
&\quad+\Bigl(\frac{P}{(\Delta T-\Delta T_{0})^{2}}\Bigr)^{2}u^{2}(\Delta T)\\[4pt]
&\quad+\Bigl(\frac{P}{(\Delta T-\Delta T_{0})^{2}}\Bigr)^{2}u^{2}(\Delta T_{0}) .
\end{aligned}
\]

Because \(G=P/(\Delta T-\Delta T_{0})\),

\[
\frac{P}{(\Delta T-\Delta T_{0})^{2}}=\frac{G}{\Delta T-\Delta T_{0}}.
\]

Substituting this yields

\[
\begin{aligned}
u^{2}(G)&=
\Bigl(\frac{G}{P}\Bigr)^{2}u^{2}(P)
+\Bigl(\frac{G}{\Delta T-\Delta T_{0}}\Bigr)^{2}u^{2}(\Delta T)
+\Bigl(\frac{G}{\Delta T-\Delta T_{0}}\Bigr)^{2}u^{2}(\Delta T_{0})\\[4pt]
&=G^{2}\Biggl[
\Bigl(\frac{u(P)}{P}\Bigr)^{2}
+\Bigl(\frac{u(\Delta T)}{\Delta T-\Delta T_{0}}\Bigr)^{2}
+\Bigl(\frac{u(\Delta T_{0})}{\Delta T-\Delta T_{0}}\Bigr)^{2}
\Biggr].
\end{aligned}
\]

Taking the square‑root gives the expression shown in (2).

---

**2.3  Alternative form using the denominator variance**

Define the denominator  

\[
D=\Delta T-\Delta T_{0}.
\]

Because \(\Delta T\) and \(\Delta T_{0}\) are independent,

\[
u^{2}(D)=u^{2}(\Delta T)+u^{2}(\Delta T_{0}).
\]

Hence the two terms that contain the temperature‑difference uncertainties can be combined as  

\[
\Bigl(\frac{u(\Delta T)}{D}\Bigr)^{2}+\Bigl(\frac{u(\Delta T_{0})}{D}\Bigr)^{2}
=\frac{u^{2}(\Delta T)+u^{2}(\Delta T_{0})}{D^{2}}
=\frac{u^{2}(D)}{D^{2}} .
\]

Inserting this into (2) leads to the compact version (3).

---

**3.  Relative (fractional) uncertainty**

Dividing (2) by \(|G|\) gives the relative standard uncertainty:

\[
\boxed{
\frac{u(G)}{|G|}=
\sqrt{
\Bigl(\frac{u(P)}{P}\Bigr)^{2}
+\Bigl(\frac{u(\Delta T)}{\Delta T-\Delta T_{0}}\Bigr)^{2}
+\Bigl(\frac{u(\Delta T_{0})}{\Delta T-\Delta T_{0}}\Bigr)^{2}
}
}
\tag{4}
\]

or, equivalently,

\[
\frac{u(G)}{|G|}
=
\sqrt{
\Bigl(\frac{u(P)}{P}\Bigr)^{2}
+\frac{u^{2}(\Delta T)+u^{2}(\Delta T_{0})}{(\Delta T-\Delta T_{0})^{2}}
}.
\tag{5}
\]

---

**4.  Edge cases and practical notes**

* **Denominator approaching zero** – If \(\Delta T-\Delta T_{0}\) becomes very small, the terms  

  \[
  \frac{u(\Delta T)}{\Delta T-\Delta T_{0}},\;
  \frac{u(\Delta T_{0})}{\Delta T-\Delta T_{0}}
  \]

  grow without bound. In the limiting case \(\Delta T = \Delta T_{0}\) the quantity \(G\) is mathematically undefined (division by zero). In a real experiment this situation must be avoided: the measurement should be made at a sufficiently large temperature difference (or the calibration offset must be measured with enough precision) so that \(|\Delta T-\Delta T_{0}|\gg\sqrt{u^{2}(\Delta T)+u^{2}(\Delta T_{0})}\).

* **Large relative uncertainties** – Even when the denominator is not strictly zero, a small value will dominate the relative uncertainty. For example, if \(u(\Delta T)=u(\Delta T_{0})=0.1\;{\rm K}\) and \(\Delta T-\Delta T_{0}=0.2\;{\rm K}\), the temperature‑difference contribution to the relative uncertainty is  

  \[
  \sqrt{\frac{0.1^{2}+0.1^{2}}{0.2^{2}}}= \sqrt{\frac{0.02}{0.04}}= \sqrt{0.5}\approx 0.71\;(71\%).
  \]

  Such a large contribution often makes the final result unreliable, prompting the experimenter to increase \(\Delta T\) or improve the temperature‑difference measurement.

* **Power uncertainty** – The term \((u(P)/P)^{2}\) is usually small if the heater power can be measured to better than a few percent. In cryogenic setups, however, the power measurement may also be limited by systematic effects (e.g., heat leak corrections), which are not captured by the simple independent‑uncertainty model.

---

**5.  (Optional) Remarks on the independence assumption**

The derivation above assumes that the three input quantities are **uncorrelated**, i.e. the covariance terms in the GUM formula are zero:

\[
u(P,\Delta T)=u(P,\Delta T_{0})=u(\Delta T,\Delta T_{0})=0.
\]

In many cryogenic thermal‑conductance experiments this assumption can be questionable:

* **Common temperature reference** – Both \(\Delta T\) (the temperature difference across the sample at a given heater power) and \(\Delta T_{0}\) (the baseline difference with the heater off) are often measured with the *same* pair of thermometers (or the same sensor). Consequently, any drift or calibration error of the thermometers appears in both \(\Delta T\) and \(\Delta T_{0}\) with the **same sign**, generating a **positive correlation**. The true covariance term would be  

  \[
  u(\Delta T,\Delta T_{0}) = r\;u(\Delta T)\,u(\Delta T_{0}),
  \]

  where \(r\) is the correlation coefficient (0 ≤ r ≤ 1 for a common‑mode error).

* **Effect on the uncertainty** – If a non‑zero correlation exists, the variance formula acquires an extra term:

  \[
  u^{2}(G)= \dots + 2\,
  \Bigl(\frac{\partial G}{\partial\Delta T}\Bigr)
  \Bigl(\frac{\partial G}{\partial\Delta T_{0}}\Bigr)
  u(\Delta T,\Delta T_{0}).
  \]

  Using the expressions from step 2.1, this becomes  

  \[
  2\Bigl(\frac{G}{D}\Bigr)^{2}\,r\,u(\Delta T)u(\Delta T_{0}),
  \]

  which **reduces** the overall uncertainty because the two temperature‑difference uncertainties partially cancel when they are positively correlated (the baseline offset tracks the measurement offset). In the extreme case of perfect correlation (\(r=1\)), the combined variance simplifies to  

  \[
  u^{2}(G)=G^{2}\Bigl[\Bigl(\frac{u(P)}{P}\Bigr)^{2}
  +\Bigl(\frac{u(\Delta T)-u(\Delta T_{0})}{D}\Bigr)^{2}\Bigr],
  \]

  i.e., the **difference** of the two temperature‑difference uncertainties appears, not their sum.

* **Practical recommendation** – If the experimental setup uses the same sensors for the two temperature‑difference measurements, it is advisable to **evaluate the correlation** (e.g., by repeatedly measuring the baseline and the active difference without changing the sample) and, when significant, include the covariance term in the uncertainty budget. The simple independent‑uncertainty formula (2) would otherwise overestimate the uncertainty, leading to overly conservative results.

---

**Summary**

* Combined standard uncertainty (independent inputs):  

  \[
  u(G)=|G|
  \sqrt{
  \Bigl(\frac{u(P)}{P}\Bigr)^{2}
  +\Bigl(\frac{u(\Delta T)}{\Delta T-\Delta T_{0}}\Bigr)^{2}
  +\Bigl(\frac{u(\Delta T_{0})}{\Delta T-\Delta T_{0}}\Bigr)^{2}
  }.
  \]

* Relative uncertainty  

  \[
  \frac{u(G)}{|G|}=
  \sqrt{
  \Bigl(\frac{u(P)}{P}\Bigr)^{2}
  +\frac{u^{2}(\Delta T)+u^{2}(\Delta T_{0})}{(\Delta T-\Delta T_{0})^{2}}
  }.
  \]

* Beware of the denominator becoming small; the uncertainty blows up as \((\Delta T-\Delta T_{0})^{-1}\).

* The independence assumption may break down in cryogenic setups where the same thermometers define both \(\Delta T\) and \(\Delta T_{0}\); accounting for a possible positive correlation can reduce the reported uncertainty.
