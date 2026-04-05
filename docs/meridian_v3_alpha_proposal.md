# Meridian v3 Architecture Proposal: Proper Alpha Signal Design

## The Problem with Current Architecture

Meridian v2 has THREE separate scores that are blended with hand-written 
weights (40/30/30). The blend formula, the weights, and the direction 
logic are all ad-hoc decisions made at 4am. This is not how quant funds 
work.

The specific contradiction: PICK has TCN=0.95 (model says "go up") but 
direction=SHORT (system says "go down"). The TCN and the selection logic 
disagree because they answer different questions using different data.

## How Quant Funds Actually Do It

From Grinold & Kahn ("Active Portfolio Management"), AQR, and Lopez de 
Prado ("Advances in Financial Machine Learning"), the standard quant 
pipeline is:

```
Alpha Model → Risk Model → Portfolio Optimizer → Execution
```

### Alpha Model
Outputs ONE number per ticker: **Expected Return E[r]**.
- Positive E[r] → LONG candidate
- Negative E[r] → SHORT candidate  
- |E[r]| → conviction (larger magnitude = higher conviction)

There is no separate "direction" assignment. There is no "factor_rank" 
blended with "tcn_score." There is ONE model that outputs ONE number.

### Risk Model
Estimates covariance matrix, factor exposures, beta. Used to ADJUST 
position sizes and constraints, NOT to pick stocks.

### Portfolio Optimizer
Takes E[r] from alpha model + covariance from risk model → optimizes 
portfolio to maximize Sharpe ratio (return per unit risk). Goes long 
the highest E[r] stocks, short the lowest E[r] stocks.

## What This Means for Meridian

### Current (v2) — Hand-Written Blend
```
factor_rank (side-aware percentile) ──┐
tcn_score (classifier probability)  ──┤── hand-written blend → final_score
lgbm_score (classifier probability) ──┘
                                         + separate direction from residual_alpha
```

Problems:
1. Direction and scoring are decoupled → contradictions
2. Blend weights (40/30/30) are arbitrary
3. factor_rank is a percentile, not a return prediction
4. Classifier outputs (0-1 probability) ≠ expected returns

### Proposed (v3) — Learned Alpha Signal
```
19 factors (raw values) ──┐
64-day history ───────────┤── ML Model → E[r] per ticker
market regime ────────────┘
                              ↓
                    E[r] > 0 → LONG
                    E[r] < 0 → SHORT
                    |E[r]| = conviction
                              ↓
                    Risk Model → position sizing
                              ↓
                    Top 30 LONG + Bottom 30 SHORT
```

### How to Get There

**Phase 1: Calibration Layer (Quick Win)**

Keep the existing TCN and LGBM classifiers. Add a calibration layer 
that converts their probabilities into expected returns:

```python
# Train a simple linear model on walk-forward test sets:
# Input: [tcn_prob, lgbm_prob, factor_vector]
# Output: actual 5-day forward return

from sklearn.linear_model import Ridge

# On each WF test window:
X = np.column_stack([tcn_probs, lgbm_probs, factor_matrix])
y = actual_5d_returns

calibrator = Ridge(alpha=1.0)
calibrator.fit(X, y)

# At inference:
E_r = calibrator.predict(X_live)
# E_r is now a SINGLE number per ticker
# Positive → LONG, Negative → SHORT, |E_r| → conviction
```

This is the Grinold & Kahn "information ratio" approach — you have 
multiple signals (IC > 0) and you combine them into a single alpha 
using a learned combination, not a hand-written one.

**Phase 2: Direct Return Prediction (Better)**

Retrain the TCN to predict RETURNS directly instead of classifying.
Your TCN regression collapsed on Colab — but that was with MSE loss 
on raw returns. The fix:

1. Use Huber loss (robust to outliers) instead of MSE
2. Predict RANK of returns (0-1) instead of raw returns
3. Use the TBM-style data augmentation but with continuous labels:
   - forward_return_5d directly, winsorized at ±10%

The advantage: ONE model outputs ONE number (expected return).
No calibration layer needed. No blend formula. No direction confusion.

**Phase 3: Portfolio Optimization (Professional)**

Replace the simple "top 30 / bottom 30" selection with mean-variance 
optimization:

```python
from scipy.optimize import minimize

def optimize_portfolio(expected_returns, cov_matrix, max_positions=30):
    """
    Maximize: w @ E[r] - lambda * w @ Sigma @ w
    Subject to: sum(|w|) <= 1, |w_i| <= max_weight
    """
    n = len(expected_returns)
    
    def objective(w):
        ret = w @ expected_returns
        risk = w @ cov_matrix @ w
        return -(ret - 0.5 * risk)  # negative because we minimize
    
    constraints = [
        {'type': 'ineq', 'fun': lambda w: 1 - np.sum(np.abs(w))},
    ]
    bounds = [(-1/max_positions, 1/max_positions)] * n
    
    result = minimize(objective, np.zeros(n), method='SLSQP',
                      bounds=bounds, constraints=constraints)
    
    weights = result.x
    # Positive weights → LONG, Negative weights → SHORT
    return weights
```

This automatically:
- Determines direction (sign of weight)
- Determines position size (magnitude of weight)
- Accounts for correlation (doesn't pick 5 correlated tech stocks)
- Maximizes risk-adjusted return (Sharpe)

## Implementation Roadmap

| Phase | What | Effort | When |
|---|---|---|---|
| **Option D** | Invert TCN/LGBM for shorts | 1 line | NOW (tonight) |
| **Phase 1** | Ridge calibrator on WF data | 1 day | After backfill |
| **Phase 2** | TCN return regression | 2 days | After Phase 1 |
| **Phase 3** | Mean-variance optimizer | 2 days | After Phase 2 |

## What Changes Per Phase

### After Option D (Tonight)
- Shorts get inverted ML scores → no more contradictions
- Direction still from residual_alpha → not ideal but functional
- Hand-written blend weights remain → works but not optimal

### After Phase 1 (Next Week)
- ONE learned alpha signal per ticker (E[r])
- Direction from sign of E[r] → no contradictions possible
- Blend weights learned from data, not hand-written
- factor_rank becomes an INPUT to the calibrator, not a separate score

### After Phase 2 (Week After)
- ONE model (TCN) outputs expected return directly
- No calibration layer needed
- No classification → no probability-to-return conversion
- Cleanest architecture: factors → TCN → E[r] → selection

### After Phase 3 (Production)
- Professional portfolio construction
- Correlation-aware position sizing
- Maximum Sharpe optimization
- This is what AQR, Two Sigma, and DE Shaw do

## Key Insight

The factor_rank, tcn_score, and lgbm_score are not three "votes" to be 
blended. They are three INPUTS to an alpha model. The alpha model 
outputs one number. That number determines everything.

Think of it like this:
- factor_rank = "how good does this stock look today?" (cross-sectional)
- tcn_score = "how good has this stock's pattern been?" (temporal)
- lgbm_score = "how does this stock compare to history?" (cross-sectional)

These are THREE VIEWS of the same question: "will this stock go up?"
The answer should be ONE number, not three blended scores.

## References

- Grinold & Kahn, "Active Portfolio Management" — the IC/IR framework
- Lopez de Prado, "Advances in Financial Machine Learning" — meta-labeling, 
  walk-forward validation, feature importance
- AQR, "Building a Better Long-Short Equity Portfolio" — separating alpha 
  from beta, portfolio construction
- Kakushadze, "101 Formulaic Alphas" — alpha combination methodology
