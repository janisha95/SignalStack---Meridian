# STAGE 3: Factor Engine — v2_factor_engine.py (Shell + Architecture)

**Status:** SPEC COMPLETE — ready for review
**Depends on:** Stage 2 (v2_prefilter.py returns ~3k ticker DataFrame)

---

## What Stage 3 Does

For every ticker in the ~3k prefiltered universe, compute a vector of ~34 continuous
factor scores. Output is a factor matrix (3k rows × 34 columns) passed to Stage 4.

NO BUY/SELL decisions. NO strategies. Just continuous numbers per ticker.

---

## Architecture

### Module Organization

```
v2_factor_engine.py          ← Shell: orchestrates all modules
  ├── factors/
  │   ├── __init__.py
  │   ├── m1_technical_core.py    ← 18 factors (Spec 3A)
  │   ├── m2_structural_phase.py  ← 5 factors  (Spec 3B)
  │   ├── m3_damage_shortside.py  ← 6 factors  (Spec 3B)
  │   ├── m4_mean_reversion.py    ← 4 factors  (Spec 3C)
  │   └── m5_market_context.py    ← 14 factors (Spec 3C)
  └── config/
      └── factor_registry.json    ← Single source of truth for all factors
```

### Universal Module Signature

Every factor module exports ONE function with this exact signature:

```python
def compute_factors(
    df: pd.DataFrame,           # ticker's OHLCV (200+ bars, columns: date, open, high, low, close, volume)
    spy_df: pd.DataFrame,       # SPY OHLCV (pre-loaded once, passed to every call)
    vix: float,                 # Current VIX level (scalar)
    sector: str | None,         # Ticker's GICS sector from sector_map (None if unmapped)
    universe_stats: dict,       # Pre-computed universe-level stats (see below)
) -> dict[str, float]           # {factor_name: value} — NaN for missing/error
```

`universe_stats` is computed ONCE before the per-ticker loop:
```python
universe_stats = {
    "market_breadth": 0.62,          # % of universe with close > MA50
    "advance_decline_ratio": 1.35,   # up tickers / down tickers today
    "sector_returns": {              # avg 10d return per sector
        "Technology": 0.023,
        "Financials": -0.011,
        ...
    },
    "spy_5d_return": 0.015,          # SPY 5-day return
    "vix_252d_percentile": 0.72,     # VIX percentile over 252 trading days
}
```

### Data Flow

```
Stage 2 output (3k tickers with regime, price, etc.)
  ↓
v2_factor_engine.py loads full OHLCV for all 3k tickers from v2_universe.db
  ↓
Pre-compute: SPY once, VIX once, universe_stats once
  ↓
For each ticker (ThreadPoolExecutor, 8 workers):
    df = ohlcv[ticker]
    factors = {}
    factors.update(m1_technical_core.compute_factors(df, spy_df, vix, sector, universe_stats))
    factors.update(m2_structural_phase.compute_factors(df, spy_df, vix, sector, universe_stats))
    factors.update(m3_damage_shortside.compute_factors(df, spy_df, vix, sector, universe_stats))
    factors.update(m4_mean_reversion.compute_factors(df, spy_df, vix, sector, universe_stats))
    factors.update(m5_market_context.compute_factors(df, spy_df, vix, sector, universe_stats))
  ↓
Output: DataFrame (3k rows × 34+ factor columns)
  ↓
Save to DB: factor_matrix_daily table (date, ticker, factor1, factor2, ...)
  ↓
Pass to Stage 4 (ML Scoring)
```

### Extensibility Design (CRITICAL — adding factors later)

**Problem we're solving:** When we add a new factor in 3 months, we don't want to
change the ML scorer, the orchestrator, or anything outside the factor engine.

**Solution: Factor Registry**

`config/factor_registry.json` is the single source of truth:

```json
{
  "version": "1.0",
  "factors": [
    {
      "name": "directional_conviction",
      "module": "m1_technical_core",
      "type": "continuous",
      "range": "z-score",
      "description": "z-score of (DI+ minus DI-)",
      "added_version": "1.0",
      "active": true
    },
    {
      "name": "wyckoff_phase",
      "module": "m2_structural_phase",
      "type": "continuous",
      "range": "-1 to 1",
      "description": "Phase encoded: ACCUM=1, DISTRIB=-1, others=0",
      "added_version": "1.0",
      "active": true
    }
    // ... all 34 factors
  ]
}
```

**How adding a factor works:**

1. Add the computation to the relevant module (e.g., `m1_technical_core.py`)
2. Add an entry to `factor_registry.json` with `"active": true`
3. The factor engine automatically picks it up (reads registry, calls modules)
4. The ML scorer reads the registry to know which columns to expect
5. Next retrain includes the new factor. No code changes to scorer.

**How REMOVING a factor works:**

1. Set `"active": false` in the registry (don't delete the entry)
2. Factor engine skips it
3. Old models still work (they ignore columns they weren't trained on)
4. Next retrain drops it

**How the ML scorer uses the registry:**

```python
# In v2_ml_scorer.py (Stage 4):
registry = json.load(open("config/factor_registry.json"))
active_factors = [f["name"] for f in registry["factors"] if f["active"]]
X = factor_matrix[active_factors]  # only active columns
prediction = model.predict(X)
```

This means the model automatically adapts to whatever factors are active.
Retraining includes new factors. Inference uses whatever the model was trained on
(stored in model sidecar JSON).

### Error Handling Per Ticker

If a module throws an exception for a ticker, that factor gets NaN.
The ticker is NOT dropped — other modules still run. The ML scorer handles NaN
(LightGBM natively supports NaN features).

```python
try:
    m1_result = m1_technical_core.compute_factors(df, spy_df, vix, sector, universe_stats)
except Exception as e:
    logger.warning(f"M1 failed for {ticker}: {e}")
    m1_result = {name: float('nan') for name in M1_FACTOR_NAMES}
```

---

## 1. Input Contract

### Required Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| Prefiltered DataFrame | Stage 2 | DataFrame with ticker, regime, price, dollar_volume, bars_available, atr_pct, adx, sector | ~3k rows |
| v2 DB | Stage 1 | SQLite with daily_bars table | For loading full OHLCV |
| Sector map | config/ticker_sector_map.json | JSON dict | 621 tickers mapped |
| Factor registry | config/factor_registry.json | JSON | Defines which factors to compute |

### Assumptions

- Stage 2 has run successfully (prefiltered DataFrame has 1,000-6,000 tickers)
- v2_universe.db has ≥50 bars per surviving ticker
- SPY and VIX (^VIX or VIXY proxy) data is available

---

## 2. Output Contract

### Primary Output: Factor matrix DataFrame (in-memory)

| Column | Type | Notes |
|--------|------|-------|
| ticker | str | From prefilter |
| date | str | Today's date (YYYY-MM-DD) |
| regime | str | From prefilter |
| All 34 factor columns | float | NaN if computation failed |

### Secondary Output: Written to DB

Table `factor_matrix_daily` in v2_universe.db:
```sql
CREATE TABLE IF NOT EXISTS factor_matrix_daily (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    -- All factor columns as REAL
    directional_conviction REAL,
    momentum_acceleration REAL,
    ... (all 34)
    PRIMARY KEY (date, ticker)
);
```

Also write to cache_meta:
- `factor_engine_run_at`: ISO timestamp
- `factor_engine_tickers`: count
- `factor_engine_nan_rate`: % of NaN values in the matrix
- `factor_engine_elapsed_seconds`: runtime

---

## 3. Success Test

### Smoke Test
```bash
cd ~/SS/Meridian
python3 stages/v2_factor_engine.py --dry-run
# Should print: factor count, ticker count, estimated time
```

### Expected Ranges

| Metric | Expected | Red Flag |
|--------|----------|----------|
| Factor count | 34 | Not 34 (registry mismatch) |
| Tickers processed | 2,000 – 5,000 | < 1,000 |
| NaN rate | < 10% | > 25% (computation issues) |
| Elapsed | 2 – 5 minutes | > 10 minutes |

---

## 4. Fail Condition

### Hard Fail

| Condition | Action |
|-----------|--------|
| Prefilter DataFrame empty | Exit code 1 |
| v2_universe.db missing | Exit code 1 |
| SPY not in DB | Exit code 1 |
| factor_registry.json missing | Exit code 1 |
| > 50% of tickers produce all-NaN factor vectors | Exit code 1 |

### Soft Warning

| Condition | Action |
|-----------|--------|
| NaN rate > 10% | Warn |
| Any single factor NaN > 30% | Warn — that factor may have a bug |
| Elapsed > 5 minutes | Warn |

---

## What NOT to Do

- Do NOT make BUY/SELL decisions — factors are continuous values only
- Do NOT import from S1 at runtime — copy computation logic
- Do NOT fetch data per-ticker — OHLCV is bulk-loaded from DB
- Do NOT fetch SPY per-ticker — pre-load once, pass as parameter
- Do NOT drop tickers on module errors — set NaN, continue
- Do NOT hardcode factor names in the engine — read from registry

---

## Acceptance Criteria

- [ ] `stages/v2_factor_engine.py` exists and orchestrates all 5 modules
- [ ] `stages/factors/` directory with m1 through m5 module files
- [ ] `config/factor_registry.json` lists all 34 factors
- [ ] Each module has `compute_factors()` with the universal signature
- [ ] Factor matrix has 34 active factor columns
- [ ] NaN rate < 10% on real data
- [ ] SPY loaded once, passed as parameter (not fetched per-ticker)
- [ ] ThreadPoolExecutor with configurable worker count
- [ ] factor_matrix_daily table created and populated
- [ ] cache_meta updated with run stats
- [ ] Adding a factor = add to module + add to registry (no other changes)
- [ ] Removing a factor = set active=false in registry (no code changes)
- [ ] Per-ticker errors produce NaN, don't crash the engine
- [ ] No imports from S1 code at runtime
- [ ] `ast.parse()` passes on all files
- [ ] All unit tests pass
- [ ] **Performance:** completes within 5 minutes on 3k tickers
