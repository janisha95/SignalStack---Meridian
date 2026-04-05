# STAGE 2: Prefilter — v2_prefilter.py

**Status:** SPEC COMPLETE — ready for build
**Depends on:** Stage 1 (v2_cache_warm.py must have populated v2_universe.db)

---

## What Stage 2 Does

Filters the full universe (~11k tickers) down to ~3k quality tickers. Fail-closed.
Tags each survivor with a market regime. Output is a clean DataFrame passed to Stage 3.

This is a FILTER, not a scorer. It removes junk. Everything that survives goes to
the Factor Engine.

---

## Filter Explanations (why each filter exists)

### Filter 1: Price floor (> $1.00)

Stocks trading below $1.00 are "penny stocks." We exclude them because:
- Extremely volatile: a $0.50 stock moving to $0.55 is a 10% move. Too noisy for ML.
- Terrible liquidity: wide bid-ask spreads eat profits on execution.
- Prop firms restrict them: FTMO doesn't allow trading sub-$1 stocks.
- Poor data quality: yfinance/Alpaca have gaps, splits, stale prices for these.

We start at $1.00 (not $5.00) to keep legitimate small-caps in the $1-5 range.
If the universe is too noisy after first run, tighten to $5.00.

### Filter 2: Dollar volume floor (> $500k daily average)

Dollar volume = price × volume. A stock might have high volume but at $0.10/share,
the actual dollars changing hands are tiny. $500k/day minimum ensures:
- Enough liquidity to enter/exit positions without moving the price.
- Institutional participation (smart money doesn't trade illiquid names).
- Realistic execution: bracket orders need liquidity to fill at expected prices.

### Filter 3: Suffix exclusions (.WS, .WT, .U, .R)

These ticker suffixes indicate special security types, NOT regular common stocks:

- **.WS = Warrants**: A warrant gives you the RIGHT to buy a stock at a specific
  price in the future. It's a derivative, not the stock itself. Example: DKNG.WS
  is a DraftKings warrant. Warrants have different pricing dynamics, can expire
  worthless, and don't follow normal technical patterns.

- **.WT = Warrants** (alternate naming): Same as .WS, different exchange convention.

- **.U = Units**: A bundled package of one share + one warrant sold together.
  Example: PSTH.U was a Pershing Square SPAC unit (1 share + 1/9 warrant). Units
  trade at different prices than the underlying stock.

- **.R = Rights**: A right gives existing shareholders the privilege to buy
  additional shares at a discount. Short-lived, low-liquidity, not a common stock.

All four are byproducts of SPAC IPOs (Special Purpose Acquisition Companies).
Our factor model (RSI, MACD, Wyckoff phases, etc.) is designed for common equities.
These derivatives don't follow the same patterns.

### Filter 4: NaN guard (minimum 50 valid bars)

We need at least 50 bars of OHLCV history to compute basic indicators like RSI(14),
ATR(14), and moving averages. Tickers with fewer bars are either:
- Newly listed (not enough history to compute factors)
- Delisted/suspended (stale data)
- Data quality issues (gaps in the feed)

50 bars is conservative — we actually need 200 for MA200, but 50 is the minimum
to compute ANY useful factor. The factor engine will handle tickers with 50-200
bars by using shorter lookbacks where needed.

---

## 1. Input Contract

### Required Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| v2 DB | Stage 1 output | SQLite at `~/SS/Meridian/data/v2_universe.db` | Must have `daily_bars` table populated |
| cache_meta validation | Stage 1 | `validation_status = 'PASS'` in cache_meta table | If validation failed, Stage 2 must not run |

### Optional Inputs

| Input | Default | Notes |
|-------|---------|-------|
| `--min-price` | 1.00 | Minimum close price in USD |
| `--min-dollar-volume` | 500000 | Minimum avg daily dollar volume |
| `--min-bars` | 50 | Minimum valid close bars required |
| `--dry-run` | False | Print stats without writing output |

### Assumptions

- Stage 1 has run successfully (v2_universe.db exists and is populated)
- daily_bars table has at least 7,000 distinct tickers
- SPY exists in the DB with current data (Stage 1 validation gate ensures this)

### Forbidden / Invalid Input

- v2_universe.db missing or empty → hard abort
- cache_meta.validation_status = 'FAIL' → hard abort (Stage 1 failed)
- SPY not in daily_bars → hard abort (needed for regime computation)

---

## 2. Output Contract

### Primary Output: Prefiltered DataFrame (in-memory)

Returned as a Python dict or pandas DataFrame to the orchestrator.
NOT written to disk as a file — passed in-memory to Stage 3.

| Column | Type | Notes |
|--------|------|-------|
| ticker | str | e.g., AAPL |
| regime | str | TRENDING / CHOPPY / VOLATILE / UNKNOWN |
| price | float | Latest close price |
| dollar_volume | float | avg(close × volume) over last 20 bars |
| bars_available | int | Count of valid close bars in DB |
| atr_pct | float | ATR(14) / close — volatility measure |
| adx | float | Wilder's ADX(14) — trend strength |
| sector | str or None | From ticker_sector_map.json (621 mapped, rest None) |

### Expected Size

| Metric | Expected Range |
|--------|---------------|
| Input tickers | 8,000 – 12,000 |
| After price filter | 7,000 – 10,000 |
| After dollar volume filter | 3,000 – 5,000 |
| After suffix exclusion | 2,800 – 4,800 |
| After NaN/bars guard | 2,500 – 4,500 |
| Final survivors | ~3,000 |

### Secondary Output: Prefilter stats written to cache_meta

Write to cache_meta table in v2_universe.db:
- `prefilter_input_count`: total tickers
- `prefilter_survivors`: count after all filters
- `prefilter_excluded_price`: count removed by price floor
- `prefilter_excluded_volume`: count removed by dollar volume
- `prefilter_excluded_suffix`: count removed by suffix
- `prefilter_excluded_bars`: count removed by min bars
- `prefilter_regime_distribution`: JSON e.g. `{"TRENDING":1200,"CHOPPY":800,"VOLATILE":600,"UNKNOWN":400}`
- `prefilter_run_at`: ISO timestamp

### Who Consumes This Output

- Stage 3 (Factor Engine): receives the ~3k ticker DataFrame
- Stage 7 (Orchestrator): reads stats from cache_meta for reporting

---

## 3. Success Test

### Smoke Test

```bash
cd ~/SS/Meridian
python3 stages/v2_prefilter.py --dry-run
# Should print filter cascade with counts
# Should show regime distribution
# Should NOT write to DB
```

### Unit Tests (test_v2_prefilter.py)

1. Tickers with close < $1.00 are removed
2. Tickers with avg dollar volume < $500k are removed
3. Tickers ending in .WS, .WT, .U, .R are removed
4. Tickers with < 50 valid bars are removed
5. SPY always survives all filters
6. Every survivor has a regime tag (TRENDING/CHOPPY/VOLATILE/UNKNOWN)
7. Survivor count between 1,000 and 6,000
8. No negative prices in output
9. Aborts if DB missing
10. Aborts if cache_meta.validation_status = FAIL
11. Running twice produces same results (idempotent)

### Expected Ranges

| Metric | Expected | Red Flag |
|--------|----------|----------|
| Survivors | 2,000 – 5,000 | < 1,000 or > 6,000 |
| UNKNOWN regime | < 30% | > 30% (ADX computation issue) |
| Price filter removals | 500 – 2,000 | > 5,000 (too aggressive) |
| Elapsed | < 60 seconds | > 120 seconds |

---

## 4. Fail Condition

### Hard Fail (abort pipeline)

| Condition | Action |
|-----------|--------|
| v2_universe.db missing | Exit code 1 |
| daily_bars table empty | Exit code 1 |
| cache_meta.validation_status = FAIL | Exit code 1 |
| SPY not in daily_bars | Exit code 1 |
| survivor_count = 0 | Exit code 1 |
| Unhandled exception | Exit code 1, log error |

### Soft Warning (log + continue)

| Condition | Action |
|-----------|--------|
| survivor_count < 1,000 | Warn — universe too small |
| survivor_count > 6,000 | Warn — consider tightening thresholds |
| > 50% excluded by one filter | Warn — one filter dominating |
| UNKNOWN regime > 30% | Warn — ADX computation issue |
| Ticker with > 20% daily move in survivors | Warn + flag (don't remove — could be real earnings) |

---

## Implementation Blueprint

### File: `~/SS/Meridian/stages/v2_prefilter.py`

### Regime Classification

```python
def classify_regime(adx: float, atr_expansion: bool = False) -> str:
    """
    Classify market regime from ADX value.
    
    TRENDING:  ADX >= 25 (strong directional trend)
    CHOPPY:    ADX 15-25 (range-bound, mean reversion territory)
    VOLATILE:  ADX < 15 AND ATR expanding (low trend but high movement)
    UNKNOWN:   ADX < 15 AND no ATR expansion (default)
    
    Note: VOLATILE requires checking if ATR is expanding while ADX is low.
    This catches stocks that are moving a lot but without clear direction.
    If unsure, default to CHOPPY (not UNKNOWN).
    """
    if adx >= 25:
        return 'TRENDING'
    elif adx >= 15:
        return 'CHOPPY'
    elif atr_expansion:
        return 'VOLATILE'
    else:
        return 'UNKNOWN'
```

### ADX Computation (Wilder's method)

Use Wilder's smoothing (alpha = 1/14) for ADX, +DI, -DI. This is the industry
standard (matches Bloomberg, TradingView, etc.). Do NOT use ewm(span=14) which
gives different results. S1 had a bug where S2 used ewm(span=14) but S1 used
Wilder's — Meridian standardizes on Wilder's.

### Filter Sequence (pseudocode)

```python
def run_prefilter(db_path, min_price=1.0, min_dollar_vol=500000, min_bars=50):
    # 1. Check preconditions
    #    - DB exists
    #    - validation_status = PASS
    #    - SPY in daily_bars
    
    # 2. Get aggregate stats per ticker (efficient SQL, not full OHLCV load)
    stats = query("""
        SELECT ticker,
               COUNT(*) as bar_count,
               -- latest close (subquery for most recent date)
               (SELECT close FROM daily_bars d2 
                WHERE d2.ticker = d1.ticker 
                ORDER BY date DESC LIMIT 1) as latest_close
        FROM daily_bars d1
        GROUP BY ticker
    """)
    
    # 3. Get 20-day dollar volume average (separate query, recent bars only)
    vol_stats = query("""
        SELECT ticker, AVG(close * volume) as avg_dollar_vol
        FROM daily_bars
        WHERE date >= date('now', '-30 days')
        GROUP BY ticker
    """)
    
    # 4. Apply filters in sequence, counting exclusions:
    #    a. Price floor: latest_close >= min_price
    #    b. Dollar volume: avg_dollar_vol >= min_dollar_vol
    #    c. Suffix: ticker NOT ending in .WS, .WT, .U, .R
    #    d. Min bars: bar_count >= min_bars
    
    # 5. For survivors ONLY: load full OHLCV and compute ADX, ATR
    #    (Don't load OHLCV for filtered-out tickers — waste of memory)
    
    # 6. Classify regime per ticker
    
    # 7. Look up sector from config/ticker_sector_map.json
    
    # 8. Write stats to cache_meta
    
    # 9. Return DataFrame
```

### Performance Note

Do NOT load all OHLCV for all 11k tickers into memory. Use SQL aggregates to
filter first (steps 2-4), then load full OHLCV only for the ~3k survivors
(step 5). This keeps memory usage reasonable and completes in < 60 seconds.

---

## Copy from S1

| S1 File | What to copy | What to change |
|---------|-------------|----------------|
| `signalstack_prefilter.py` | ADX computation (Wilder's), ATR computation | Remove top-N selection. Pass ALL survivors. |
| `signalstack_router.py` | Regime classification thresholds | Tag only, don't route. |

---

## What NOT to Do

- Do NOT select top-N tickers — pass ALL survivors to Stage 3
- Do NOT make BUY/SELL decisions — this is a filter, not a signal generator
- Do NOT write a separate output file — return DataFrame in-memory
- Do NOT import from S1 code at runtime — copy logic, don't import
- Do NOT skip the validation_status check
- Do NOT remove tickers with >20% daily moves — warn but keep (could be real)

---

## Acceptance Criteria

- [ ] `stages/v2_prefilter.py` exists and runs without errors
- [ ] Reads from `data/v2_universe.db` daily_bars table
- [ ] Checks cache_meta.validation_status before running
- [ ] Applies 4 filters: price ($1), dollar_volume ($500k), suffix (.WS/.WT/.U/.R), min_bars (50)
- [ ] Tags each survivor with regime (TRENDING/CHOPPY/VOLATILE/UNKNOWN)
- [ ] Returns DataFrame with: ticker, regime, price, dollar_volume, bars_available, atr_pct, adx, sector
- [ ] Survivor count between 1,000 and 6,000 on real data
- [ ] SPY always survives
- [ ] No negative prices in output
- [ ] Filter counts written to cache_meta
- [ ] `--dry-run` prints stats without writing
- [ ] Aborts if DB missing, empty, or validation_status = FAIL
- [ ] No imports from S1 code at runtime
- [ ] All unit tests pass
- [ ] `ast.parse()` passes
- [ ] **Idempotent:** same input produces same output
- [ ] **Performance:** completes within 60 seconds on 11k tickers
