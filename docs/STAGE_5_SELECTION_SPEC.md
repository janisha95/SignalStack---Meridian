# STAGE 5: Selection — v2_selection.py

**Status:** SPEC COMPLETE — ready for build
**Depends on:** Stage 4 ML predictions (or mock predictions for testing)

---

## What Stage 5 Does

Takes ML predictions for ~3k tickers, strips market beta, ranks by residual
alpha (idiosyncratic predicted return), and outputs top LONG + SHORT shortlists.

This is ~100 lines of math. No ML, no data fetching.

---

## Pipeline

```
Input: DataFrame with columns [ticker, predicted_return, regime, sector, price, ...]
  ↓
Step 1: Compute rolling beta per ticker (60-day regression vs SPY returns)
  ↓
Step 2: Strip market component: residual = predicted_return - (beta × spy_predicted_return)
  ↓
Step 3: Rank by residual (positive residuals = LONG candidates, negative = SHORT)
  ↓
Step 4: Take top N LONG + top N SHORT
  ↓
Output: shortlist DataFrame [ticker, direction, predicted_return, residual_alpha, beta, rank]
```

---

## 1. Input Contract

| Input | Source | Format |
|-------|--------|--------|
| Predictions DataFrame | Stage 4 output | ticker, predicted_return (signed float), plus factor columns |
| SPY predicted return | Stage 4 output | Single float (SPY's predicted 5d return) |
| Ticker betas | Computed from OHLCV | 60-day rolling regression slope vs SPY |
| v2_universe.db | Stage 1 | For loading historical returns to compute beta |

### CLI Arguments

| Flag | Default | Notes |
|------|---------|-------|
| `--top-n` | 15 | Number of picks per side (15 LONG + 15 SHORT) |
| `--min-residual` | 0.005 | Minimum absolute residual to include (0.5%) |
| `--dry-run` | False | Print shortlist without writing |
| `--debug` | None | Ticker to print full selection math |

---

## 2. Output Contract

### Primary Output: shortlist DataFrame (in-memory + written to DB)

| Column | Type | Notes |
|--------|------|-------|
| ticker | str | |
| direction | str | LONG or SHORT |
| predicted_return | float | Raw ML prediction (signed) |
| beta | float | 60-day rolling beta vs SPY |
| market_component | float | beta × spy_predicted_return |
| residual_alpha | float | predicted_return - market_component |
| rank | int | 1 = best residual in that direction |
| regime | str | From prefilter |
| sector | str | From sector map |
| price | float | Latest close |

### DB Table: shortlist_daily

```sql
CREATE TABLE IF NOT EXISTS shortlist_daily (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    predicted_return REAL,
    beta REAL,
    residual_alpha REAL,
    rank INTEGER,
    regime TEXT,
    sector TEXT,
    price REAL,
    PRIMARY KEY (date, ticker)
);
```

---

## 3. Implementation

### Beta Computation

```python
def compute_beta(ticker_returns: pd.Series, spy_returns: pd.Series, window: int = 60) -> float:
    """Rolling beta from OLS regression: ticker_return = alpha + beta * spy_return."""
    if len(ticker_returns) < window or len(spy_returns) < window:
        return 1.0  # default to market beta
    t = ticker_returns.iloc[-window:]
    s = spy_returns.iloc[-window:]
    cov = t.cov(s)
    var = s.var()
    if var == 0:
        return 1.0
    return cov / var
```

### Residual Alpha

```python
spy_pred = predictions.loc[predictions['ticker'] == 'SPY', 'predicted_return'].iloc[0]

for ticker in predictions['ticker']:
    beta = compute_beta(ticker_returns[ticker], spy_returns, window=60)
    market_component = beta * spy_pred
    residual = predictions.loc[ticker, 'predicted_return'] - market_component
```

### Ranking

```python
# LONG: positive residual, descending
longs = df[df['residual_alpha'] > min_residual].nlargest(top_n, 'residual_alpha')
longs['direction'] = 'LONG'
longs['rank'] = range(1, len(longs) + 1)

# SHORT: negative residual, ascending (most negative first)
shorts = df[df['residual_alpha'] < -min_residual].nsmallest(top_n, 'residual_alpha')
shorts['direction'] = 'SHORT'
shorts['rank'] = range(1, len(shorts) + 1)
```

---

## 4. Acceptance Criteria

- [ ] `stages/v2_selection.py` exists
- [ ] Computes beta from 60-day rolling regression
- [ ] Strips market component from predictions
- [ ] Ranks by residual alpha (not raw prediction)
- [ ] Outputs top N LONG + top N SHORT
- [ ] Writes to shortlist_daily table
- [ ] --debug shows full math for one ticker
- [ ] Progress logging per OPERATIONAL_STANDARDS.md
- [ ] Works with mock predictions (for testing before Stage 4B)
- [ ] No S1 imports
- [ ] QA report at qa_report_stage5.md
