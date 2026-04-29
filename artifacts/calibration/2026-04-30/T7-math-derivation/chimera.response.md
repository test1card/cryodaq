

### 1. Formula for \(u(G)\) in terms of input uncertainties:

The uncertainty in thermal conductance \(G\) is:

\[
u(G) = \sqrt{ 
  \left( \frac{u(P)}{\Delta T - \Delta T_0} \right)^2 + 
  \left( \frac{P \cdot u(\Delta T)}{(\Delta T - \Delta T_0)^2} \right)^2 + 
  \left( \frac{P \cdot u(\Delta T_0)}{(\Delta T - \Delta T_0)^2} \right)^2 
}
\]

or equivalently (in relative form):

\[
\frac{u(G)}{|G|} = \sqrt{ 
  \left( \frac{u(P)}{P} \right)^2 + 
  \frac{u(\Delta T)^2 + u(\Delta T_0)^2}{(\Delta T - \Delta T_0)^2} 
}
\]

---

### 2. Derivation via GUM Methodology (Partial Derivatives)

**Step 1: Define the functional relationship**  
Given \( G = \frac{P}{\Delta T - \Delta T_0} \), let \( D = \Delta T - \Delta T_0 \) to simplify notation:  
\[
G = \frac{P}{D}
\]

**Step 2: Compute partial derivatives**  
- **Partial derivative w.r.t. \(P\)**:  
  \[
  \frac{\partial G}{\partial P} = \frac{1}{D}
  \]
  
- **Partial derivative w.r.t. \(\Delta T\)**:  
  \[
  \frac{\partial G}{\partial \Delta T} = \frac{\partial G}{\partial D} \cdot \frac{\partial D}{\partial \Delta T} = \left( -\frac{P}{D^2} \right) \cdot 1 = -\frac{P}{D^2}
  \]
  
- **Partial derivative w.r.t. \(\Delta T_0\)**:  
  \[
  \frac{\partial G}{\partial \Delta T_0} = \frac{\partial G}{\partial D} \cdot \frac{\partial D}{\partial \Delta T_0} = \left( -\frac{P}{D^2} \right) \cdot (-1) = \frac{P}{D^2}
  \]

**Step 3: Propagate uncertainties**  
For uncorrelated inputs, the combined uncertainty \(u(G)\) is:  
\[
u(G)^2 = \left( \frac{\partial G}{\partial P} \right)^2 u(P)^2 + \left( \frac{\partial G}{\partial \Delta T} \right)^2 u(\Delta T)^2 + \left( \frac{\partial G}{\partial \Delta T_0} \right)^2 u(\Delta T_0)^2
\]

Substitute the partial derivatives:  
\[
u(G)^2 = \left( \frac{1}{D} \right)^2 u(P)^2 + \left( -\frac{P}{D^2} \right)^2 u(\Delta T)^2 + \left( \frac{P}{D^2} \right)^2 u(\Delta T_0)^2
\]

Simplify:  
\[
u(G)^2 = \frac{u(P)^2}{D^2} + \frac{P^2 u(\Delta T)^2}{D^4} + \frac{P^2 u(\Delta T_0)^2}{D^4}
\]

Factor common terms:  
\[
u(G)^2 = \frac{1}{D^2} \left[ u(P)^2 + \frac{P^2}{D^2} \left( u(\Delta T)^2 + u(\Delta T_0)^2 \right) \right]
\]

**Step 4: Express in terms of \(G\)**  
Since \( G = \frac{P}{D} \), we substitute \( P = G D \):  
\[
u(G)^2 = \frac{1}{D^2} \left[ u(P)^2 + G^2 \left( u(\Delta T)^2 + u(\Delta T_0)^2 \right) \right]
\]

Take the square root for absolute uncertainty:  
\[
u(G) = \frac{1}{D} \sqrt{ u(P)^2 + G^2 \left( u(\Delta T)^2 + u(\Delta T_0)^2 \right) }
\]

---

### 3. Relative Uncertainty \( \frac{u(G)}{|G|} \)

From \( G = \frac{P}{D} \), we know \( |G| = \frac{|P|}{D} \) (assuming \( D > 0 \)). Divide \(u(G)\) by \(|G|\):  
\[
\frac{u(G)}{|G|} = \frac{1}{D} \sqrt{ u(P)^2 + G^2 \left( u(\Delta T)^2 + u(\Delta T_0)^2 \right) } \cdot \frac{D}{|P|}
\]

Simplify using \( \frac{G}{|P|} = \frac{1}{D} \):  
\[
\frac{u(G)}{|G|} = \sqrt{ \frac{u(P)^2}{P^2} + \frac{u(\Delta T)^2 + u(\Delta T_0)^2}{D^2} }
\]

Final result for relative uncertainty:  
\[
\boxed{
\frac{u(G)}{|G|} = \sqrt{ \left( \frac{u(P)}{P} \right)^2 + \frac{u(\Delta T)^2 + u(\Delta T_0)^2}{(\Delta T - \Delta T_0)^2} }
}
\]

---

### 4. Edge Cases

- **Denominator near zero (\( \Delta T \to \Delta T_0 \))**:  
  The relative uncertainty \( \frac{u(G)}{|G|} \) diverges as \( (\Delta T - \Delta T_0)^{-1} \). **This reflects critical instability**: small errors in \( \Delta T \) or \( \Delta T_0 \) cause large errors in \( G \). In practice, \( \Delta T \) should be measured far from \( \Delta T_0 \).

- **Power near zero (\( P \to 0 \))**:  
  The first term \( \left( \frac{u(P)}{P} \right)^2 \) dominates, leading to high uncertainty if \( P \) is small.

---

### 5. Independence Assumption in Cryogenic Experiments

The assumption that \( \Delta T \) and \( \Delta T_0 \) are uncorrelated may **fail** if:
- Both share a common temperature sensor (e.g., \( \Delta T = T_2 - T_1 \), \( \Delta T_0 = T_{2,\text{offset}} - T_{1,\text{offset}} \)).
- Sensor drift or noise affects \( \Delta T \) and \( \Delta T_0 \) similarly.

**Implications**:  
Correlation would introduce covariance terms, modifying \( u(G) \):  
\[
u(G)^2 = \dots + 2 \frac{\partial G}{\partial \Delta T} \frac{\partial G}{\partial \Delta T_0} \cdot u(\Delta T, \Delta T_0)
\]  
where \( u(\Delta T, \Delta T_0) \) is the covariance. If correlated, a more detailed error model is needed.
