# REBUILD Stage 5 From Scratch

## Context
v2_selection.py has been rewritten multiple times and is in an unknown state.
DELETE THE EXISTING FILE and rebuild from the original specs below.

## Source Specs
1. STAGE_5_SELECTION_SPEC.md (original, in project knowledge)
2. ba_spec_tcn_wire_v2.md (TCN wiring, from our session)
3. Option D (invert TCN for shorts)

## Step 0: BACKUP
```bash
cp ~/SS/Meridian/stages/v2_selection.py ~/SS/Meridian/stages/v2_selection.py.broken_backup
```

## Step 1: DELETE and recreate v2_selection.py from scratch

The file must implement EXACTLY this pipeline:

### Input
- predictions_daily table (ticker, predicted_return, regime, sector, price)
- SPY predicted_return from same table
- daily_bars table for 60-day return history (beta computation)
- TCN scorer output (optional — falls back to 0.5)

### Pipeline
```
1. Load predictions from predictions_daily (or generate mock)
2. Load 60-day returns for beta computation
3. Compute beta per ticker (60-day covariance/variance vs SPY)
4. Compute residual_alpha = predicted_return - (beta × spy_predicted_return)
5. Direction: residual_alpha > 0 → LONG, < 0 → SHORT
6. Split into LONG and SHORT pools
7. Score TCN for all tickers (or 0.5 fallback)
8. Compute factor_rank WITHIN each pool:
   - LONGS: factor_rank = rank(residual_alpha, pct=True) among LONGS only
   - SHORTS: factor_rank = rank(-residual_alpha, pct=True) among SHORTS only
     (negate so most negative residual gets highest rank)
9. Compute final_score:
   - LONGS: final_score = 0.60 * factor_rank + 0.40 * tcn_score
   - SHORTS: final_score = 0.60 * factor_rank + 0.40 * (1.0 - tcn_score)
     (Option D: invert TCN for shorts — low TCN = bearish = good short)
10. Sort LONGS by final_score DESC, take top 30
11. Sort SHORTS by final_score DESC, take top 30
12. Assign rank = 1, 2, 3... sequentially after sorting
13. Write to shortlist_daily table
```

### Key Details

BETA COMPUTATION:
```python
def compute_beta(ticker_returns, spy_returns, window=60):
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

BETA CLAMP: Clamp beta to [-3.0, 3.0] to prevent extreme values.

FACTOR_RANK IS SIDE-AWARE:
- Computed WITHIN each direction pool (longs ranked vs longs, shorts vs shorts)
- Based on residual_alpha magnitude within each pool
- This prevents shorts from being disadvantaged by a global long-biased rank

OPTION D (Short TCN Inversion):
- For SHORTS, the TCN score is inverted: (1.0 - tcn_score)
- A low TCN score (bearish signal) produces a HIGH inverted value
- This means the most bearish tickers rank highest among shorts

TCN FALLBACK:
- When TCN model files are missing, tcn_score = 0.5 for all tickers
- final_score = 0.60 * factor_rank + 0.40 * 0.5 = 0.60 * factor_rank + 0.20
- Rankings driven by factor_rank alone in this mode

### DB Schema (shortlist_daily)
```sql
CREATE TABLE IF NOT EXISTS shortlist_daily (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    predicted_return REAL,
    beta REAL,
    market_component REAL,
    residual_alpha REAL,
    rank INTEGER,
    regime TEXT,
    sector TEXT,
    price REAL,
    top_shap_factors TEXT,
    factor_rank REAL,
    tcn_score REAL,
    final_score REAL,
    PRIMARY KEY (date, ticker)
);
```

### CLI Arguments
--db           Path to v2_universe.db (default: data/v2_universe.db)
--top-n        Picks per side (default: 30)
--min-residual Minimum |residual_alpha| to include (default: 0.001)
--dry-run      Print without writing to DB
--debug TICKER Print full math for one ticker
--mock         Use mock predictions (for testing without Stage 4)
--show-all     Show entire ranked universe, not just top N

### Progress Logging
Print progress every 500 tickers during beta computation.
Print top 3 LONG and top 3 SHORT with their scores after ranking.
Print total time elapsed.

### Mock Mode
When --mock is used:
- Generate mock predicted_return for all prefiltered tickers
- predicted_return = random uniform [-0.10, +0.10]
- SPY predicted_return = 0.03 (3%)
- TCN scores come from the real TCN scorer if model files exist,
  otherwise 0.5 for all tickers

## Step 2: Verify

```bash
cd ~/SS/Meridian

# Compile check
python3 -c "import ast; ast.parse(open('stages/v2_selection.py').read()); print('SYNTAX OK')"

# Run with real TCN
python3 stages/v2_selection.py

# Check output
python3 -c "
import sqlite3
con = sqlite3.connect('data/v2_universe.db')
d = con.execute('SELECT MAX(date) FROM shortlist_daily').fetchone()[0]
print(f'Date: {d}')
for dir in ['LONG','SHORT']:
    rows = con.execute('''SELECT rank, ticker, final_score, tcn_score, factor_rank, residual_alpha
        FROM shortlist_daily WHERE direction=? AND date=? ORDER BY rank LIMIT 5''', (dir,d)).fetchall()
    print(f'\n=== TOP 5 {dir} ===')
    for r in rows:
        blend_check = 0.60 * r[4] + 0.40 * (r[3] if dir=='LONG' else 1.0-r[3])
        match = 'OK' if abs(r[2] - blend_check) < 0.001 else f'MISMATCH: expected {blend_check:.4f}'
        print(f'  #{r[0]} {r[1]} final={r[2]:.4f} tcn={r[3]:.3f} fr={r[4]:.3f} resid={r[5]:.4f} blend={match}')
con.close()
"
```

### Expected Output
- 60 total rows (30 LONG + 30 SHORT)
- LONGs: high tcn_score, positive residual_alpha
- SHORTs: low tcn_score (Option D makes low TCN = high final_score)
- factor_rank is 0-1 percentile within each side's pool
- Blend formula check passes for every row
- Ranks are sequential 1, 2, 3...

## Step 3: DO NOT TOUCH
- stages/tcn_scorer.py (DO NOT MODIFY)
- stages/v2_api_server.py (leave as is for now)
- stages/v2_orchestrator.py (leave as is)
- stages/v2_risk_filters.py (leave as is)
- Any UI files (leave as is)

py_compile the new v2_selection.py after writing.
