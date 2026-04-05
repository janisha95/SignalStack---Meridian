# CODEX — INVESTIGATE Meridian LONG TCN ETF Bias (DIAGNOSTIC ONLY)

## DO NOT FIX ANYTHING. ONLY COLLECT DATA AND REPORT.

The Meridian LONG TCN consistently ranks ETFs above individual stocks.
This happened BEFORE the Stage 5 simplification. We need to understand
WHY before attempting any fix.

## Investigation 1: What types of instruments are in the top 30 LONGs?

```bash
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT s.ticker, s.direction, 
    ROUND(s.tcn_long_score, 4) as tcn,
    ROUND(s.factor_rank, 4) as fr,
    ROUND(s.final_score, 4) as final,
    ROUND(f.atr_pct, 4) as atr_pct,
    ROUND(f.residual_alpha, 6) as res_alpha,
    ROUND(f.beta, 4) as beta,
    ROUND(f.daily_return, 6) as daily_ret,
    ROUND(f.volume_20d_avg, 0) as vol_20d
FROM shortlist_daily s
LEFT JOIN factor_matrix_daily f ON s.ticker = f.ticker AND s.date = f.date
WHERE s.date = (SELECT MAX(date) FROM shortlist_daily)
    AND s.direction = 'LONG'
ORDER BY s.tcn_long_score DESC
"
```

## Investigation 2: Compare TCN scores — ETFs vs individual stocks

```bash
# Get ALL predictions (not just shortlist) and categorize
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT p.ticker, 
    ROUND(p.tcn_long_score, 4) as tcn_long,
    ROUND(p.tcn_short_score, 4) as tcn_short,
    ROUND(f.atr_pct, 4) as atr_pct,
    ROUND(f.beta, 4) as beta,
    ROUND(f.residual_alpha, 6) as res_alpha,
    ROUND(f.volume_20d_avg, 0) as vol
FROM predictions_daily p
LEFT JOIN factor_matrix_daily f ON p.ticker = f.ticker AND p.date = f.date
WHERE p.date = (SELECT MAX(date) FROM predictions_daily)
    AND p.tcn_long_score > 0.90
ORDER BY p.tcn_long_score DESC
LIMIT 50
"
```

## Investigation 3: What does the factor engine produce for ETFs vs stocks?

```bash
# Compare factor distributions: pick known ETFs and known stocks
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT ticker,
    ROUND(atr_pct, 4) as atr,
    ROUND(beta, 4) as beta,
    ROUND(residual_alpha, 6) as res_alpha,
    ROUND(momentum_impulse, 4) as mom_imp,
    ROUND(directional_conviction, 4) as dir_conv,
    ROUND(volatility_rank, 4) as vol_rank,
    ROUND(volume_participation, 4) as vol_part,
    ROUND(effort_vs_result, 4) as evr,
    ROUND(damage_depth, 4) as dmg,
    ROUND(rs_vs_spy_10d, 4) as rs10,
    ROUND(rs_vs_spy_20d, 4) as rs20
FROM factor_matrix_daily
WHERE date = (SELECT MAX(date) FROM factor_matrix_daily)
    AND ticker IN ('SCHD','GFLW','DFAU','NOBL','SPYD',
                   'ORCL','TTC','BTDR','ARQT','RGC',
                   'AAPL','NVDA','TSLA','META','AMZN')
ORDER BY ticker
"
```

## Investigation 4: What features does the TCN actually see?

The LONG TCN uses 19 features from config.json:
directional_conviction, momentum_acceleration, momentum_impulse,
volume_participation, volume_flow_direction, effort_vs_result,
volatility_rank, volatility_acceleration, wick_rejection, bb_position,
ma_alignment, dist_from_ma20_atr, wyckoff_phase, phase_confidence,
damage_depth, rollover_strength, rs_vs_spy_10d, rs_vs_spy_20d, rs_momentum

Check if these features systematically favor ETFs:
```bash
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT ticker,
    ROUND(directional_conviction, 4) as dc,
    ROUND(momentum_impulse, 4) as mi,
    ROUND(volatility_rank, 4) as vr,
    ROUND(ma_alignment, 4) as ma,
    ROUND(damage_depth, 4) as dd,
    ROUND(wyckoff_phase, 2) as wp,
    ROUND(phase_confidence, 4) as pc,
    ROUND(bb_position, 4) as bb
FROM factor_matrix_daily
WHERE date = (SELECT MAX(date) FROM factor_matrix_daily)
    AND ticker IN ('SCHD','NOBL','DFAU','GFLW','SPYD',
                   'ORCL','TTC','BTDR','ARQT','RGC')
ORDER BY ticker
"
```

## Investigation 5: Is the Stage 3 factor engine computing correctly?

```bash
# Check for columns that are all the same value (broken computation)
python3 -c "
import sqlite3
import pandas as pd
con = sqlite3.connect('/Users/sjani008/SS/Meridian/data/v2_universe.db')
df = pd.read_sql('''
    SELECT * FROM factor_matrix_daily
    WHERE date = (SELECT MAX(date) FROM factor_matrix_daily)
''', con)
con.close()

print(f'Total tickers: {len(df)}')
print(f'Columns: {len(df.columns)}')
print()
# Check each numeric column for variance
for col in df.select_dtypes(include='number').columns:
    std = df[col].std()
    nulls = df[col].isna().sum()
    zeros = (df[col] == 0).sum()
    print(f'{col:30s} std={std:.6f} nulls={nulls} zeros={zeros}')
"
```

## Investigation 6: Is residual_alpha even being computed?

```bash
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT 
    COUNT(*) as total,
    SUM(CASE WHEN residual_alpha IS NULL THEN 1 ELSE 0 END) as null_ra,
    SUM(CASE WHEN residual_alpha = 0 THEN 1 ELSE 0 END) as zero_ra,
    ROUND(AVG(residual_alpha), 6) as avg_ra,
    ROUND(MIN(residual_alpha), 6) as min_ra,
    ROUND(MAX(residual_alpha), 6) as max_ra
FROM factor_matrix_daily
WHERE date = (SELECT MAX(date) FROM factor_matrix_daily)
"
```

## Investigation 7: Check the TCN model input pipeline

Is the Stage 4 TCN scorer building the feature matrix correctly?
Does it match the 19 features in the config?

```bash
grep -n "features\|feature_cols\|config\|model_features\|input" ~/SS/Meridian/stages/tcn_scorer.py | head -20

# Check if features are loaded from config
python3 -c "
import json
from pathlib import Path

# LONG TCN config
long_cfg = json.loads((Path.home() / 'SS/Meridian/models/tcn_pass_v1/config.json').read_text())
print('LONG TCN features:', long_cfg['features'])
print('Count:', len(long_cfg['features']))

# SHORT TCN config  
short_cfg = json.loads((Path.home() / 'SS/Meridian/models/tcn_short_v1/config.json').read_text())
print()
print('SHORT TCN features:', short_cfg['features'])
print('Count:', len(short_cfg['features']))
"
```

## Investigation 8: Historical pattern — was this always the case?

```bash
# Check last 5 days of shortlists
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT date, direction, ticker, ROUND(tcn_long_score, 4) as tcn, ROUND(final_score, 4) as final
FROM shortlist_daily
WHERE direction = 'LONG'
ORDER BY date DESC, tcn_long_score DESC
LIMIT 30
"
```

## OUTPUT FORMAT

After running ALL investigations, create a summary report:

```
=== MERIDIAN LONG TCN DIAGNOSTIC REPORT ===

1. TOP 30 LONG COMPOSITION:
   - X ETFs vs Y individual stocks
   - Average TCN score for ETFs: ___
   - Average TCN score for stocks: ___
   
2. FACTOR PROFILE (ETFs vs Stocks):
   Feature              ETF avg    Stock avg    Difference
   volatility_rank      ___        ___          ___
   damage_depth         ___        ___          ___
   (etc)

3. FACTOR ENGINE HEALTH:
   - Columns with zero variance: ___
   - Columns with >50% null: ___
   - Columns with >50% zeros: ___

4. RESIDUAL_ALPHA STATUS:
   - Computed: yes/no
   - Distribution: ___

5. TCN FEATURE ALIGNMENT:
   - Config features match factor_matrix columns: yes/no
   - Mismatches: ___

6. DIAGNOSIS:
   [Your assessment of root cause]
```

DO NOT FIX ANYTHING. Report the data. We decide the fix after seeing the evidence.
