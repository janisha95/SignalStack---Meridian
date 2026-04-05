# STAGE 3C: Modules 4 + 5 — Mean Reversion + Market Context (18 factors)

**Files:**
- `stages/factors/m4_mean_reversion.py` (4 factors)
- `stages/factors/m5_market_context.py` (14 factors)

**Copy from S1:**
- `mr.py` Strategy6Scanner → Module 4 (remove hard gates, keep continuous scores)
- `srs.py` RS computation → Module 5
- New computations for breadth, sector RS, options, VIX percentile

**Depends on:** OHLCV per ticker + SPY + VIX + universe_stats + options_daily table

---

## Module 4: Mean Reversion Quality — 4 factors

Detects pullback quality in uptrending stocks. In S1, the MR strategy had hard
gates (leadership filter → pullback filter → trigger filter) that rejected 99.9%
of tickers. In Meridian, each gate becomes a continuous score for EVERY ticker.

| # | Factor | Computation | Range | S1 Source |
|---|--------|-------------|-------|-----------|
| 1 | `leadership_score` | Composite: above SMA200 + SMA50 rising + RS>0 + liquidity | 0 to 1 | mr.py — remove hard gate |
| 2 | `pullback_score` | Composite: shock magnitude + RSI2 washout + BB penetration | 0 to 1 | mr.py — remove hard gate |
| 3 | `shock_magnitude` | abs(2-bar return) / ATR% | ratio | mr.py |
| 4 | `setup_score` | Weighted: 0.4×leadership + 0.4×pullback + 0.2×trigger quality | 0 to 1 | mr.py |

### Key Change from S1

S1's MR strategy had a 3-phase cascade:
1. Leadership filter: above SMA200? SMA50 rising? RS positive? → REJECT if any fail
2. Pullback filter: RSI2 < 10? Shock > threshold? BB penetration? → REJECT if fail
3. Trigger filter: RSI2 hook? Volume confirm? → REJECT if fail

**Meridian replaces hard gates with continuous scores:**
- Leadership: each condition contributes 0.25 to the score (4 conditions × 0.25 = 1.0 max)
- Pullback: RSI2 washout depth + shock magnitude + BB penetration depth (weighted)
- Trigger quality: RSI2 hook confirmation (0 or 1)

```python
def leadership_score(df, spy_df):
    score = 0.0
    close = df['close'].iloc[-1]
    sma200 = df['close'].rolling(200).mean().iloc[-1]
    sma50 = df['close'].rolling(50).mean().iloc[-1]
    sma50_prev = df['close'].rolling(50).mean().iloc[-6]
    
    if close > sma200: score += 0.25          # above long-term trend
    if sma50 > sma50_prev: score += 0.25      # SMA50 rising
    # RS > 0 (ticker outperforming SPY over 20d)
    if len(spy_df) >= 20:
        ticker_ret = (close / df['close'].iloc[-21]) - 1
        spy_ret = (spy_df['close'].iloc[-1] / spy_df['close'].iloc[-21]) - 1
        if ticker_ret > spy_ret: score += 0.25
    # Adequate dollar volume (> $1M/day avg)
    dollar_vol = (df['close'] * df['volume']).tail(20).mean()
    if dollar_vol > 1_000_000: score += 0.25
    
    return score  # 0.0 to 1.0

def pullback_score(df):
    score = 0.0
    closes = df['close']
    # RSI2 washout depth (lower = deeper washout = higher score)
    rsi2 = compute_rsi(closes, period=2)
    if rsi2 <= 5: score += 0.4
    elif rsi2 <= 10: score += 0.3
    elif rsi2 <= 20: score += 0.15
    
    # Shock magnitude
    ret_2bar = abs((closes.iloc[-1] / closes.iloc[-3]) - 1)
    atr_pct = compute_atr(df, 14) / closes.iloc[-1]
    shock = ret_2bar / atr_pct if atr_pct > 0 else 0
    score += min(0.3, shock * 0.1)  # cap contribution at 0.3
    
    # BB penetration
    bb_lower = closes.rolling(20).mean().iloc[-1] - 2 * closes.rolling(20).std().iloc[-1]
    if closes.iloc[-1] < bb_lower: score += 0.3
    elif closes.iloc[-1] < bb_lower * 1.01: score += 0.15  # near lower band
    
    return min(1.0, score)
```

---

## Module 5: Market Context — 14 factors

Universe-level and cross-sectional factors. Some are per-ticker (RS, options),
some are universe-wide (breadth, advance/decline) passed via universe_stats.

**Per-ticker factors (computed per ticker):**

| # | Factor | Computation | Range | S1 Source |
|---|--------|-------------|-------|-----------|
| 1 | `rs_vs_spy_10d` | 10d return minus SPY 10d return | ratio | srs.py |
| 2 | `rs_vs_spy_20d` | 20d return minus SPY 20d return | ratio | srs.py |
| 3 | `rs_momentum` | rs_10d minus rs_20d (improving or deteriorating) | ratio | srs.py |
| 4 | `rs_vs_sector` | Ticker 10d return minus sector avg 10d return | ratio | NEW — use sector_map + universe_stats |
| 5 | `sector_weakness` | 1.0 if sector RS < 0 AND ticker RS < sector, else 0.0 | 0 or 1 | NEW |
| 6 | `options_pcr` | Put/Call ratio from options_daily table | ratio | Stage 1 options pull |
| 7 | `options_unusual_vol` | Unusual options volume ratio from options_daily | ratio | Stage 1 options pull |
| 8 | `dollar_volume_log` | log10(price × avg volume 20d) | log scale | Have |
| 9 | `price_quality` | log10(price) — higher = more institutional | log scale | Have |
| 10 | `volume_climax` | Today volume / 60d max volume | 0 to 1 | NEW — build |

**Universe-level factors (same value for all tickers, from universe_stats):**

| # | Factor | Computation | Range | Notes |
|---|--------|-------------|-------|-------|
| 11 | `market_breadth` | % of universe with close > MA50 | 0 to 1 | Computed once for entire universe |
| 12 | `advance_decline_ratio` | Up tickers / down tickers today | ratio | Computed once |
| 13 | `spy_momentum_5d` | SPY 5-day return | ratio | From SPY data |
| 14 | `vix_regime` | VIX percentile over 252 days | 0 to 1 | From VIX history |

### RS Computation (from S1 srs.py)

```python
def rs_vs_spy(ticker_closes, spy_closes, period):
    if len(ticker_closes) < period + 1 or len(spy_closes) < period + 1:
        return float('nan')
    ticker_ret = (ticker_closes.iloc[-1] / ticker_closes.iloc[-period-1]) - 1
    spy_ret = (spy_closes.iloc[-1] / spy_closes.iloc[-period-1]) - 1
    return ticker_ret - spy_ret
```

### Sector-Relative RS (NEW)

Uses `universe_stats["sector_returns"]` which is pre-computed:

```python
def rs_vs_sector(ticker_10d_return, sector, universe_stats):
    sector_returns = universe_stats.get("sector_returns", {})
    sector_avg = sector_returns.get(sector, 0.0)
    if sector is None or sector not in sector_returns:
        return float('nan')  # unmapped ticker
    return ticker_10d_return - sector_avg
```

### Options Factors

Read from `options_daily` table in v2_universe.db (populated by Stage 1):

```python
def get_options_factors(ticker, db_path):
    con = sqlite3.connect(db_path)
    row = con.execute(
        "SELECT pcr, unusual_vol_ratio FROM options_daily WHERE ticker=? ORDER BY date DESC LIMIT 1",
        (ticker,)
    ).fetchone()
    con.close()
    if row is None:
        return {"options_pcr": float('nan'), "options_unusual_vol": float('nan')}
    return {"options_pcr": row[0], "options_unusual_vol": row[1]}
```

### Volume Climax (NEW)

```python
def volume_climax(volumes, window=60):
    if len(volumes) < window:
        return float('nan')
    max_vol = volumes.tail(window).max()
    if max_vol == 0:
        return 0.0
    return volumes.iloc[-1] / max_vol  # 0 to 1
```

### Universe Stats Pre-Computation

Computed ONCE before the per-ticker loop in v2_factor_engine.py:

```python
def compute_universe_stats(all_ohlcv: dict, spy_df, vix_history, sector_map):
    """Pre-compute universe-level stats. Called once."""
    
    # Market breadth: % of tickers with close > MA50
    above_ma50 = 0
    total = 0
    up_tickers = 0
    down_tickers = 0
    sector_returns = defaultdict(list)
    
    for ticker, df in all_ohlcv.items():
        if len(df) < 50:
            continue
        total += 1
        close = df['close'].iloc[-1]
        ma50 = df['close'].rolling(50).mean().iloc[-1]
        if close > ma50:
            above_ma50 += 1
        
        # Advance/decline
        prev_close = df['close'].iloc[-2] if len(df) >= 2 else close
        if close > prev_close:
            up_tickers += 1
        elif close < prev_close:
            down_tickers += 1
        
        # Sector returns (10d)
        sector = sector_map.get(ticker)
        if sector and len(df) >= 11:
            ret_10d = (close / df['close'].iloc[-11]) - 1
            sector_returns[sector].append(ret_10d)
    
    # SPY 5d return
    spy_5d = float('nan')
    if len(spy_df) >= 6:
        spy_5d = (spy_df['close'].iloc[-1] / spy_df['close'].iloc[-6]) - 1
    
    # VIX percentile
    vix_pct = float('nan')
    if vix_history is not None and len(vix_history) >= 252:
        current_vix = vix_history.iloc[-1]
        vix_pct = (vix_history.tail(252) < current_vix).mean()
    
    return {
        "market_breadth": above_ma50 / total if total > 0 else 0.5,
        "advance_decline_ratio": up_tickers / max(down_tickers, 1),
        "sector_returns": {s: sum(r)/len(r) for s, r in sector_returns.items()},
        "spy_5d_return": spy_5d,
        "vix_252d_percentile": vix_pct,
    }
```

---

## Tests

### test_m4_mean_reversion.py
1. Returns 4 factors in output dict
2. leadership_score bounded 0 to 1
3. pullback_score bounded 0 to 1
4. shock_magnitude >= 0
5. setup_score bounded 0 to 1
6. Leadership score = 0.0 when price below SMA200, SMA50 falling, RS negative, low volume
7. Leadership score = 1.0 when all 4 conditions met
8. Pullback score > 0.5 when RSI2 < 5 and BB penetration
9. Returns NaN on insufficient data (< 200 bars for SMA200)

### test_m5_market_context.py
1. Returns 14 factors in output dict
2. rs_vs_spy_10d is a ratio (not raw return)
3. rs_momentum = rs_10d - rs_20d (verify math)
4. rs_vs_sector returns NaN for unmapped tickers
5. sector_weakness binary (0 or 1)
6. options_pcr reads from DB (mock test)
7. options_pcr returns NaN when no options data
8. market_breadth bounded 0 to 1
9. vix_regime bounded 0 to 1
10. volume_climax bounded 0 to 1
11. dollar_volume_log > 0 for any traded stock
12. price_quality > 0 for any stock with price > $1

---

## Acceptance Criteria

- [ ] `stages/factors/m4_mean_reversion.py` exists with `compute_factors()` returning 4 keys
- [ ] `stages/factors/m5_market_context.py` exists with `compute_factors()` returning 14 keys
- [ ] MR factors computed for ALL tickers (no hard gates rejecting non-oversold)
- [ ] RS computed relative to both SPY and sector
- [ ] Options factors read from options_daily table (NaN if missing)
- [ ] Universe-level factors (breadth, A/D, VIX percentile) computed once, passed to all tickers
- [ ] volume_climax uses 60-day max, not 20-day
- [ ] No imports from S1
- [ ] All unit tests pass
- [ ] QA report generated at `qa_report_stage3c.md`
