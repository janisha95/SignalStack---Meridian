# STAGE 4A: Training Data Backfill — v2_training_backfill.py

**Status:** SPEC COMPLETE — ready for build
**Depends on:** Stage 3 factor modules (m1-m5) + v2_universe.db with 2yr OHLCV

---

## What Stage 4A Does

Generates historical training data by running Stage 3's factor modules on
every historical date, then pairing each day's factors with the ACTUAL 5-day
forward return. This produces ~1.5M training rows that Stage 4B (ML training)
uses to train LightGBM and LSTM models.

This is NOT forward-looking. For each historical date, we only use OHLCV data
available UP TO that date to compute factors. The 5-day forward return is the
actual realized return (which we know because it's historical).

**This runs ONCE to bootstrap the training set.** After that, the nightly
orchestrator appends one new row per ticker per day.

---

## How It Works

```
For date in [2024-09-01 ... 2026-03-20]:  (skip weekends/holidays)
    For ticker in prefiltered_universe:
        ohlcv_up_to_date = load OHLCV where date <= current_date
        if len(ohlcv) < 200: skip  (need history for MA200)
        
        factors = compute_all_34_factors(ohlcv_up_to_date, spy_up_to_date, ...)
        
        forward_return = (close[date+5] - close[date]) / close[date]
        # date+5 = 5 TRADING days later, not calendar days
        
        training_row = {
            date: current_date,
            ticker: ticker,
            **factors,          # 34 factor columns
            forward_return_5d: forward_return,  # target variable
            direction: 'LONG' if forward_return > 0 else 'SHORT',
        }
        
        write to training_data table
```

**Key constraint:** For any given date, we ONLY use OHLCV bars with date <= that
date. We never peek into the future. This prevents look-ahead bias.

---

## 1. Input Contract

### Required Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| v2_universe.db | Stage 1 | SQLite with daily_bars (2yr history) | 5M+ bars, 11k+ tickers |
| Prefilter logic | Stage 2 | Reuse prefilter thresholds | Apply to each historical date's snapshot |
| Factor modules | Stage 3 | m1-m5 with compute_factors() | Same modules used for live scoring |
| Factor registry | config/factor_registry.json | JSON | Know which 34 factors to compute |

### CLI Arguments

| Flag | Default | Notes |
|------|---------|-------|
| `--start-date` | 2024-09-01 | First date to backfill (need 6mo of OHLCV warmup before this) |
| `--end-date` | 5 trading days ago | Last date (must have 5d forward return available) |
| `--tickers` | all prefiltered | Comma-separated list for debugging one ticker |
| `--sample` | None | Random sample N tickers (for testing: --sample 50) |
| `--workers` | 4 | ThreadPoolExecutor worker count |
| `--batch-days` | 20 | Process N dates, write to DB, then next batch (memory management) |
| `--dry-run` | False | Compute 1 date, print stats, don't write |
| `--debug` | None | Ticker to print full factor dump for each date |

---

## 2. Output Contract

### Primary Output: training_data table in v2_universe.db

```sql
CREATE TABLE IF NOT EXISTS training_data (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    -- 34 factor columns (all REAL, NaN allowed)
    adx REAL,
    directional_conviction REAL,
    momentum_acceleration REAL,
    momentum_impulse REAL,
    volume_participation REAL,
    volume_flow_direction REAL,
    effort_vs_result REAL,
    volatility_rank REAL,
    volatility_acceleration REAL,
    wick_rejection REAL,
    bb_position REAL,
    ma_alignment REAL,
    dist_from_ma20_atr REAL,
    wyckoff_phase REAL,
    phase_confidence REAL,
    phase_age_days REAL,
    vol_bias REAL,
    structure_quality REAL,
    damage_depth REAL,
    rollover_strength REAL,
    downside_volume_dominance REAL,
    ma_death_cross_proximity REAL,
    leadership_score REAL,
    pullback_score REAL,
    shock_magnitude REAL,
    setup_score REAL,
    rs_vs_spy_10d REAL,
    rs_vs_spy_20d REAL,
    rs_momentum REAL,
    options_pcr REAL,
    options_unusual_vol REAL,
    volume_climax REAL,
    market_breadth REAL,
    vix_regime REAL,
    -- Target variable
    forward_return_5d REAL,      -- (close[date+5] / close[date]) - 1
    -- Metadata
    regime TEXT,
    sector TEXT,
    price REAL,
    PRIMARY KEY (date, ticker)
);

CREATE INDEX IF NOT EXISTS idx_training_date ON training_data(date);
CREATE INDEX IF NOT EXISTS idx_training_ticker ON training_data(ticker);
```

### Expected Size

| Metric | Expected |
|--------|----------|
| Date range | ~380 trading days (2024-09-01 to 2026-03-20) |
| Tickers per date | ~2,000-3,000 (varies by date, prefilter applied) |
| Total rows | ~800,000 - 1,200,000 |
| DB size | ~500MB - 1GB |

### Secondary Output: backfill_report.json

```json
{
    "ok": true,
    "start_date": "2024-09-01",
    "end_date": "2026-03-20",
    "trading_days_processed": 380,
    "total_rows_written": 950000,
    "avg_tickers_per_date": 2500,
    "nan_rate_overall": 0.03,
    "forward_return_coverage": 0.97,
    "elapsed_seconds": 3600,
    "factor_nan_rates": {
        "options_pcr": 0.95,
        "options_unusual_vol": 0.95,
        "adx": 0.01,
        ...
    }
}
```

---

## 3. Implementation Blueprint

### Performance Architecture

Computing 34 factors for 2,500 tickers × 380 days = 950,000 factor computations.
Each takes ~80ms (from Stage 3 benchmarks: 260s / 3,313 tickers).
Naive sequential: 950,000 × 80ms = 21 hours. Too slow.

**Optimization: Pre-load all OHLCV once, slice per-date.**

```python
def run_backfill(db_path, start_date, end_date, workers=4, batch_days=20):
    # 1. Load ALL OHLCV for ALL tickers into memory (one-time cost)
    #    ~5M rows, ~2GB RAM. This is acceptable.
    print(f"[backfill] Loading all OHLCV...", flush=True)
    all_ohlcv = load_all_ohlcv(db_path)  # dict[ticker] -> DataFrame
    spy_df = all_ohlcv.get('SPY')
    print(f"[backfill] Loaded {len(all_ohlcv)} tickers", flush=True)
    
    # 2. Get list of trading days from SPY dates
    trading_days = sorted(spy_df['date'].unique())
    trading_days = [d for d in trading_days if start_date <= d <= end_date]
    print(f"[backfill] {len(trading_days)} trading days to process", flush=True)
    
    # 3. Process in batches of batch_days
    for batch_start in range(0, len(trading_days), batch_days):
        batch = trading_days[batch_start:batch_start + batch_days]
        batch_rows = []
        
        for date_idx, current_date in enumerate(batch):
            # 4. For each date: slice OHLCV up to that date
            #    This is O(1) with pre-sorted DataFrames + searchsorted
            
            # 5. Apply prefilter logic to this date's snapshot
            #    (price > $1, dollar_vol > $500k, bars >= 50)
            survivors = prefilter_for_date(all_ohlcv, current_date)
            
            # 6. Compute universe_stats for this date
            universe_stats = compute_universe_stats_for_date(
                all_ohlcv, spy_df, current_date
            )
            
            # 7. Compute factors for each surviving ticker
            for ticker in survivors:
                df_slice = all_ohlcv[ticker][all_ohlcv[ticker]['date'] <= current_date]
                spy_slice = spy_df[spy_df['date'] <= current_date]
                
                factors = compute_all_factors(
                    df_slice, spy_slice, vix, sector, universe_stats
                )
                
                # 8. Compute 5-day forward return
                future_dates = all_ohlcv[ticker][all_ohlcv[ticker]['date'] > current_date]
                if len(future_dates) >= 5:
                    close_now = df_slice['close'].iloc[-1]
                    close_future = future_dates['close'].iloc[4]  # 5th trading day
                    forward_return = (close_future / close_now) - 1
                else:
                    forward_return = float('nan')  # too close to end of data
                
                batch_rows.append({
                    'date': current_date,
                    'ticker': ticker,
                    **factors,
                    'forward_return_5d': forward_return,
                    'regime': classify_regime(factors.get('adx', 0)),
                    'sector': sector_map.get(ticker),
                    'price': df_slice['close'].iloc[-1],
                })
            
            # Progress logging
            total_done = batch_start + date_idx + 1
            print(f"[backfill] Date {current_date}: {len(survivors)} tickers "
                  f"({total_done}/{len(trading_days)} days, "
                  f"{total_done*100//len(trading_days)}%)", flush=True)
        
        # 9. Write batch to DB
        write_training_rows(db_path, batch_rows)
        print(f"[backfill] Batch written: {len(batch_rows)} rows", flush=True)
```

### OHLCV Slicing Optimization

Don't copy DataFrames for each date. Use index-based slicing:

```python
# Pre-sort all DataFrames by date once
for ticker in all_ohlcv:
    all_ohlcv[ticker] = all_ohlcv[ticker].sort_values('date').reset_index(drop=True)

# For each date, use searchsorted to find the cutoff index
def slice_up_to_date(df, date_str):
    idx = df['date'].searchsorted(date_str, side='right')
    return df.iloc[:idx]
```

This avoids copying 500-row DataFrames 950,000 times.

### Simplified Prefilter for Backfill

Don't run the full Stage 2 prefilter for each date (too slow).
Use a simplified version that checks:
1. Latest close (as of current_date) > $1.00
2. 20-day avg dollar volume > $500k
3. At least 50 bars available up to current_date
4. Not a suffix ticker (.WS, .WT, .U, .R)

```python
def prefilter_for_date(all_ohlcv, current_date, min_price=1.0, 
                        min_dollar_vol=500000, min_bars=50):
    survivors = []
    for ticker, df in all_ohlcv.items():
        slice_df = slice_up_to_date(df, current_date)
        if len(slice_df) < min_bars:
            continue
        latest_close = slice_df['close'].iloc[-1]
        if latest_close < min_price:
            continue
        dollar_vol = (slice_df['close'] * slice_df['volume']).tail(20).mean()
        if dollar_vol < min_dollar_vol:
            continue
        if any(ticker.upper().endswith(s) for s in ('.WS', '.WT', '.U', '.R')):
            continue
        survivors.append(ticker)
    return survivors
```

### Forward Return Computation

```python
def compute_forward_return(all_ohlcv, ticker, current_date, horizon=5):
    """Compute actual forward return over next N trading days."""
    df = all_ohlcv[ticker]
    future = df[df['date'] > current_date]
    if len(future) < horizon:
        return float('nan')  # not enough future data
    close_now = df[df['date'] <= current_date]['close'].iloc[-1]
    close_future = future['close'].iloc[horizon - 1]  # 5th trading day
    return (close_future / close_now) - 1
```

### Options Data Note

Historical options data is NOT available (Stage 1 only pulls today's options).
So `options_pcr` and `options_unusual_vol` will be NaN for ALL historical rows.
LightGBM handles NaN natively — it will learn to ignore these features during
backfill training and use them only when live data is available.

---

## 4. Success Test

### Smoke Test

```bash
cd ~/SS/Meridian
python3 stages/v2_training_backfill.py --dry-run --sample 10
# Should:
#   Load OHLCV
#   Process 1 date with 10 random tickers
#   Print factor values + forward returns
#   NOT write to DB
```

### Debug Test

```bash
python3 stages/v2_training_backfill.py --debug AAPL --start-date 2025-01-02 --end-date 2025-01-10
# Should print AAPL's 34 factors + forward return for each date in the range
```

### Full Run

```bash
python3 stages/v2_training_backfill.py --start-date 2024-09-01
# Expected: ~4-6 hours for full backfill
# Progress logs every date
```

### Validation Queries After Full Run

```sql
-- Total rows
SELECT COUNT(*) FROM training_data;
-- Expected: 800,000 - 1,200,000

-- Rows per date (should be ~2,000-3,000)
SELECT date, COUNT(*) as n FROM training_data GROUP BY date ORDER BY date LIMIT 10;

-- Forward return distribution (should be roughly normal, centered near 0)
SELECT 
    ROUND(forward_return_5d * 100, 0) as pct_bucket,
    COUNT(*) as n
FROM training_data
WHERE forward_return_5d IS NOT NULL
GROUP BY pct_bucket
ORDER BY pct_bucket;

-- NaN rates per factor
SELECT 
    SUM(CASE WHEN adx IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as adx_nan_pct,
    SUM(CASE WHEN options_pcr IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as options_nan_pct
FROM training_data;
```

### Unit Tests (test_v2_training_backfill.py)

1. Forward return computation is correct (known price data → expected return)
2. Forward return is NaN when < 5 future bars
3. OHLCV slice only includes data up to current_date (no look-ahead)
4. Prefilter removes sub-$1 tickers for historical date
5. Training rows have all 34 factor columns + forward_return_5d
6. Duplicate (date, ticker) pairs are handled (INSERT OR REPLACE)
7. --sample limits ticker count
8. --dry-run doesn't write to DB
9. --debug prints factor dump

---

## 5. Fail Condition

### Hard Fail

| Condition | Action |
|-----------|--------|
| v2_universe.db missing | Exit code 1 |
| SPY missing from DB | Exit code 1 |
| < 100 trading days in range | Exit code 1 |
| < 500 tickers with 200+ bars | Exit code 1 |
| All factor computations return NaN for a date | Exit code 1, log the date |

### Soft Warning

| Condition | Action |
|-----------|--------|
| forward_return_5d NaN rate > 10% | Warn — expected for last 5 days |
| Factor NaN rate > 30% (except options) | Warn — computation bug |
| < 1,500 tickers on a date | Warn — unusual |
| Processing time > 8 hours | Warn |

---

## What NOT to Do

- Do NOT peek into future data when computing factors (no look-ahead bias)
- Do NOT import from S1 at runtime
- Do NOT run the full Stage 2 prefilter per date (too slow) — use simplified version
- Do NOT load OHLCV from DB per-ticker per-date (too slow) — bulk load once
- Do NOT skip progress logging
- Do NOT store raw prices as factors (only ratios/z-scores/encoded values)

---

## Acceptance Criteria

- [ ] `stages/v2_training_backfill.py` exists and runs
- [ ] Uses Stage 3 factor modules (m1-m5) — same code, not duplicated
- [ ] No look-ahead bias — factors computed only from data available at that date
- [ ] Forward return = actual 5-trading-day return
- [ ] training_data table created with 34 factor columns + forward_return_5d
- [ ] INSERT OR REPLACE for idempotence
- [ ] --dry-run, --debug, --sample flags work
- [ ] Progress logging every date
- [ ] NaN rate summary at end
- [ ] backfill_report.json written
- [ ] 800k+ rows on full run
- [ ] No S1 imports
- [ ] All unit tests pass
- [ ] `ast.parse()` passes
- [ ] QA report generated at `qa_report_stage4a.md`
