# STAGE 3A: Module 1 — Technical Core (18 factors)

**File:** `stages/factors/m1_technical_core.py`
**Copy from S1:** `rct.py` FeatureFactory z-score computations + edge family scores
**Depends on:** OHLCV DataFrame per ticker (200+ bars)

---

## What Module 1 Computes

Z-scored momentum, volume, volatility, and price structure factors.
These are the bread-and-butter technical indicators that capture short-term
directional and volume dynamics. All 18 are stationary (z-scores, percentiles,
or ratios) — no raw prices or volumes.

---

## Factor Catalogue (18 factors)

| # | Factor | Computation | Range | S1 Source |
|---|--------|-------------|-------|-----------|
| 1 | `adx` | Wilder's ADX(14) | 0-100 | Have (prefilter also computes, but engine needs its own for the matrix) |
| 2 | `directional_conviction` | z-score of (DI+ minus DI-) over 20 bars | z-score | rct.py FeatureFactory |
| 3 | `momentum_acceleration` | z-score of RSI(14) 3-bar diff over 20 bars | z-score | rct.py FeatureFactory |
| 4 | `momentum_impulse` | z-score of MACD histogram / ATR over 20 bars | z-score | rct.py FeatureFactory |
| 5 | `volume_participation` | z-score of volume / volume_ma20 over 20 bars | z-score | rct.py FeatureFactory |
| 6 | `volume_flow_direction` | z-score of OBV 5-bar diff over 20 bars | z-score | rct.py FeatureFactory |
| 7 | `effort_vs_result` | z-score of (bar range / volume) over 20 bars | z-score | rct.py FeatureFactory |
| 8 | `volatility_rank` | Percentile of ATR over 126 trading days | 0-1 | rct.py FeatureFactory |
| 9 | `volatility_acceleration` | z-score of ATR change rate over 20 bars | z-score | rct.py FeatureFactory |
| 10 | `wick_rejection` | z-score of wick bias ((high-close)-(close-low))/range over 20 bars | z-score | rct.py FeatureFactory |
| 11 | `rsi14` | Standard RSI(14) | 0-100 | Have |
| 12 | `rsi2` | RSI(2) — extreme washout detector | 0-100 | mr.py |
| 13 | `bb_position` | (close - BB_lower) / (BB_upper - BB_lower) | 0-1 | Have |
| 14 | `bb_width` | (BB_upper - BB_lower) / BB_middle | ratio | Have |
| 15 | `ma_alignment` | Encoded: price vs MA20/MA50/MA200 position | -3 to +3 | Have (scattered) |
| 16 | `dist_from_ma20_atr` | (close - MA20) / ATR | ratio | Have |
| 17 | `trend_persistence` | Consecutive bars in same direction (signed: +N for up, -N for down) | integer | NEW — build |
| 18 | `price_acceleration` | 5d return minus 20d return | ratio | NEW — build |

### Z-Score Computation Standard

All z-scored factors use the same formula:
```python
def z_score(series: pd.Series, window: int = 20) -> float:
    """Z-score of latest value relative to rolling window."""
    if len(series) < window:
        return float('nan')
    rolling_mean = series.iloc[-window:].mean()
    rolling_std = series.iloc[-window:].std()
    if rolling_std == 0 or pd.isna(rolling_std):
        return 0.0
    return (series.iloc[-1] - rolling_mean) / rolling_std
```

This is the SAME z-score computation as S1's rct.py FeatureFactory. Standardized
so all z-scored factors are comparable.

### Indicator Computation Details

**ADX (Wilder's method):**
Same as Stage 2 prefilter. Use Wilder's smoothing (alpha = 1/period), NOT ewm.

**RSI(14) and RSI(2):**
Standard Wilder RSI. For RSI(2), use period=2 — this is an extreme washout
detector that catches 2-bar panic selling (RSI2 < 10 = severely oversold).

**Bollinger Bands:**
- Middle = SMA(20)
- Upper = Middle + 2 × StdDev(20)
- Lower = Middle - 2 × StdDev(20)
- `bb_position` = (close - lower) / (upper - lower), clamped to 0-1
- `bb_width` = (upper - lower) / middle

**MA Alignment (encoded -3 to +3):**
```python
score = 0
if close > ma20: score += 1
if close > ma50: score += 1
if close > ma200: score += 1
if close < ma20: score -= 1
if close < ma50: score -= 1
if close < ma200: score -= 1
# Result: +3 = above all MAs (strong uptrend)
#         -3 = below all MAs (strong downtrend)
#          0 = mixed (transitional)
```

**Trend Persistence (NEW):**
```python
def trend_persistence(closes: pd.Series) -> int:
    """Count consecutive bars in same direction. Signed."""
    diffs = closes.diff().dropna()
    if len(diffs) == 0:
        return 0
    count = 0
    direction = 1 if diffs.iloc[-1] > 0 else -1
    for d in reversed(diffs):
        if (d > 0 and direction > 0) or (d < 0 and direction < 0):
            count += 1
        else:
            break
    return count * direction  # +N for up streak, -N for down streak
```

**Price Acceleration (NEW):**
```python
def price_acceleration(closes: pd.Series) -> float:
    """5d return minus 20d return. Positive = accelerating up. Negative = decelerating."""
    if len(closes) < 21:
        return float('nan')
    ret_5d = (closes.iloc[-1] / closes.iloc[-6]) - 1
    ret_20d = (closes.iloc[-1] / closes.iloc[-21]) - 1
    return ret_5d - ret_20d
```

---

## Tests (test_m1_technical_core.py)

1. All 18 factors returned in output dict
2. Z-scored factors have reasonable range (-5 to +5 for most tickers)
3. RSI14 bounded 0-100
4. RSI2 bounded 0-100
5. bb_position bounded 0-1 (with small float tolerance)
6. ADX bounded 0-100
7. ma_alignment bounded -3 to +3
8. trend_persistence returns signed integer
9. price_acceleration returns float
10. Returns NaN dict when given < 20 bars of data
11. Does not crash on all-zero volume data
12. Does not crash on constant price (zero volatility)

---

## Acceptance Criteria

- [ ] `stages/factors/m1_technical_core.py` exists
- [ ] `compute_factors()` returns dict with exactly 18 keys
- [ ] All z-score computations use 20-bar rolling window
- [ ] ADX uses Wilder's smoothing
- [ ] RSI uses Wilder's smoothing
- [ ] No raw prices or volumes in output (all stationary)
- [ ] Handles edge cases: < 20 bars → NaN, zero volume → NaN, constant price → 0
- [ ] No imports from S1
- [ ] QA report generated at `qa_report_stage3a.md`
