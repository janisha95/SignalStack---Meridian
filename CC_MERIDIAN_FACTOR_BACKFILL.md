# CC — Backfill Meridian factor_history for TCN v2 Features

## CONTEXT

The TCN v2 model (IC=0.105) is loaded and running, but 7 of its 19 required features are missing from `factor_history` for all dates except 2026-03-30. The scorer fills them with 0.5 neutral, degrading signal quality.

The 7 missing features:
- `momentum_impulse`
- `volume_flow_direction`
- `effort_vs_result`
- `volatility_acceleration`
- `wick_rejection`
- `rollover_strength`
- `rs_momentum`

These features ARE computed by the current factor engine (`v2_factor_engine.py`) and written to `factor_matrix_daily`. They just were never copied into `factor_history` for historical dates.

## READ FIRST

```bash
# 1. What does factor_history actually contain?
sqlite3 ~/SS/Meridian/data/v2_universe.db "PRAGMA table_info(factor_history)"

# 2. How many dates have ALL 7 missing features populated?
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT COUNT(DISTINCT date) as dates_with_all_7
FROM factor_history
WHERE momentum_impulse IS NOT NULL
  AND volume_flow_direction IS NOT NULL
  AND effort_vs_result IS NOT NULL
  AND volatility_acceleration IS NOT NULL
  AND wick_rejection IS NOT NULL
  AND rollover_strength IS NOT NULL
  AND rs_momentum IS NOT NULL
"

# 3. Does factor_matrix_daily have these features historically?
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT date, COUNT(*) as rows,
  SUM(CASE WHEN momentum_impulse IS NOT NULL THEN 1 ELSE 0 END) as has_mi,
  SUM(CASE WHEN effort_vs_result IS NOT NULL THEN 1 ELSE 0 END) as has_evr
FROM factor_matrix_daily
WHERE date >= '2025-01-01'
GROUP BY date
ORDER BY date DESC
LIMIT 10
"

# 4. How does the orchestrator write factor_history?
grep -n "factor_history\|INSERT.*factor_history\|_write_history\|_update_history" ~/SS/Meridian/stages/v2_orchestrator.py ~/SS/Meridian/stages/v2_factor_engine.py | head -20

# 5. What's the factor_history write path?
grep -n -A 10 "factor_history" ~/SS/Meridian/stages/v2_factor_engine.py | head -30
```

**Report ALL output.**

## TWO POSSIBLE SCENARIOS

### Scenario A: factor_matrix_daily HAS the 7 features historically

If `factor_matrix_daily` has `momentum_impulse` etc. for historical dates, we just need to copy them into `factor_history`:

```python
import sqlite3
import pandas as pd

DB = "/Users/sjani008/SS/Meridian/data/v2_universe.db"
con = sqlite3.connect(DB)

# The 7 features to backfill
MISSING = [
    "momentum_impulse", "volume_flow_direction", "effort_vs_result",
    "volatility_acceleration", "wick_rejection", "rollover_strength", "rs_momentum"
]

# Get all dates from factor_matrix_daily that have these features
for feat in MISSING:
    print(f"Backfilling {feat}...")
    con.execute(f"""
        UPDATE factor_history
        SET {feat} = (
            SELECT fmd.{feat}
            FROM factor_matrix_daily fmd
            WHERE fmd.date = factor_history.date
              AND fmd.ticker = factor_history.ticker
              AND fmd.{feat} IS NOT NULL
        )
        WHERE {feat} IS NULL
          AND EXISTS (
            SELECT 1 FROM factor_matrix_daily fmd
            WHERE fmd.date = factor_history.date
              AND fmd.ticker = factor_history.ticker
              AND fmd.{feat} IS NOT NULL
          )
    """)
    updated = con.execute(f"SELECT changes()").fetchone()[0]
    print(f"  Updated {updated} rows", flush=True)

con.commit()
con.close()
```

### Scenario B: factor_matrix_daily does NOT have these features historically

If the factor engine only started computing these features recently, we need to re-run the factor engine on historical dates. This is more complex:

```bash
# Check which modules compute the missing features
grep -rn "momentum_impulse\|volume_flow_direction\|effort_vs_result\|volatility_acceleration\|wick_rejection\|rollover_strength\|rs_momentum" ~/SS/Meridian/stages/factors/m*.py | head -20
```

Then we need a historical recompute script that:
1. Loads daily_bars for each historical date
2. Runs the factor modules that produce the 7 missing features
3. Updates factor_history with the results

## IMPLEMENT

Based on the diagnostic output, implement the appropriate scenario. The goal is: ALL 19 TCN v2 features populated in factor_history for at least the last 100 trading days (ideally all 643 dates).

## VERIFY

```bash
# After backfill: how many dates now have all 19 v2 features?
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT COUNT(DISTINCT date) as complete_dates
FROM factor_history
WHERE momentum_impulse IS NOT NULL
  AND volume_flow_direction IS NOT NULL
  AND effort_vs_result IS NOT NULL
  AND volatility_acceleration IS NOT NULL
  AND wick_rejection IS NOT NULL
  AND rollover_strength IS NOT NULL
  AND rs_momentum IS NOT NULL
"

# Re-run TCN scorer to verify improved signal
cd ~/SS/Meridian && python3 -c "
from stages.tcn_scorer import TCNScorer
scorer = TCNScorer()
result = scorer.score()
print(f'Scored: {len(result)} tickers')
print(f'Min: {result[\"score\"].min():.4f}')
print(f'Max: {result[\"score\"].max():.4f}')
print(f'Mean: {result[\"score\"].mean():.4f}')
"
```

## GIT

```bash
cd ~/SS/Meridian && git add -A && git commit -m "fix: backfill factor_history with 7 missing TCN v2 features"
```
