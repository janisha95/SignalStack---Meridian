# URGENT ROLLBACK + OPTION D FIX — v2_selection.py

## Context
The alpha model changes broke Stage 5. The system now shows inverse ETFs 
as top LONGs, shorts have tiny conviction, and rankings are wrong.

We need to RESTORE the 60/40 blend formula that was working before, 
plus apply the Option D fix (invert TCN for shorts) to solve the 
original directional decoupling bug.

## Files to modify
- ~/SS/Meridian/stages/v2_selection.py
- ~/SS/Meridian/stages/v2_api_server.py

## Step 1: READ the current files FIRST
```
cat ~/SS/Meridian/stages/v2_selection.py
cat ~/SS/Meridian/stages/v2_api_server.py
```
Understand the current broken state before making changes.

## Step 2: READ the original Stage 5 spec
~/SS/Meridian/docs/STAGE_5_SELECTION_SPEC.md
This is the ORIGINAL spec that was working. The pipeline should be:
1. Load TCN scores (or fallback to 0.5)
2. Load factor_rank (cross-sectional percentile, side-aware)
3. Compute beta per ticker (60-day rolling regression vs SPY)
4. Compute residual_alpha = predicted_return - (beta × spy_predicted_return)
5. Split by sign of residual_alpha: positive = LONG, negative = SHORT
6. Within each side, compute final_score using the blend formula
7. Rank by final_score descending within each side

## Step 3: RESTORE the blend formula with Option D

### For LONGS:
```python
final_score = (
    0.40 * factor_rank
    + 0.30 * tcn_score
    + 0.30 * lgbm_score   # if lgbm not available, use: 0.60 * factor_rank + 0.40 * tcn_score
)
```

### For SHORTS (Option D — INVERT TCN and LGBM):
```python
final_score = (
    0.40 * factor_rank
    + 0.30 * (1.0 - tcn_score)
    + 0.30 * (1.0 - lgbm_score)   # if lgbm not available: 0.60 * factor_rank + 0.40 * (1.0 - tcn_score)
)
```

### Why inversion for shorts:
The TCN was trained to predict P(price hits +2% before -1%).
- TCN=0.95 means "very likely to go UP" → terrible short candidate
- TCN=0.10 means "very likely to go DOWN" → great short candidate
Inverting (1 - tcn_score) for shorts means bearish TCN signals rank highest.
Factor_rank is NOT inverted because it's already computed side-aware 
(separate percentile pools for longs and shorts).

### Direction logic:
Direction comes from sign of residual_alpha (existing logic):
- residual_alpha > 0 → LONG
- residual_alpha < 0 → SHORT
This part was working before and should be kept.

### Ranking:
- LONGs: rank by final_score DESCENDING (highest = rank 1)
- SHORTs: rank by final_score DESCENDING (highest = rank 1)
  (NOT ascending — because we inverted the TCN, highest final_score 
  = most bearish signal = best short)
- Ranks must be 1, 2, 3, 4, 5... sequential

## Step 4: Keep the new UI-facing columns but populate them correctly

The UI now expects these fields. Keep them but compute from the blend:
- expected_return = predicted_return (same value, alias)
- conviction = final_score (use final_score as conviction too)
- alpha = residual_alpha (alias)
- tcn_prob = tcn_score (alias)

The DB columns added (expected_return, conviction, alpha) should still 
be written — just populated with the blend values, not the broken 
probability-weighted formula.

## Step 5: Fix v2_api_server.py

The normalize function must return:
```python
{
    "ticker": row["ticker"],
    "direction": row["direction"],
    "rank": row["rank"],
    "price": row["price"],
    "alpha": row.get("residual_alpha", 0),       # residual alpha for UI "Alpha" column
    "residual_alpha": row.get("residual_alpha", 0),
    "expected_return": row.get("predicted_return", 0),
    "conviction": row.get("final_score", 0),      # final_score drives conviction bar
    "tcn_prob": row.get("tcn_score", 0.5),
    "factor_rank": row.get("factor_rank", 0.5),
    "beta": row.get("beta", 1.0),
    "regime": row.get("regime", "UNKNOWN"),
    "sector": row.get("sector", "UNKNOWN"),
    # Legacy aliases
    "tcn_score": row.get("tcn_score", 0.5),
    "final_score": row.get("final_score", 0),
    "predicted_return": row.get("predicted_return", 0),
}
```

Key: `alpha` in the API = `residual_alpha` from DB (the beta-stripped value).
`conviction` in the API = `final_score` from DB (the blend score).
These are what the UI displays.

## Step 6: Verify

```bash
cd ~/SS/Meridian

# Compile check
python3 -c "import ast; ast.parse(open('stages/v2_selection.py').read()); print('selection OK')"
python3 -c "import ast; ast.parse(open('stages/v2_api_server.py').read()); print('api OK')"

# Re-run selection
python3 stages/v2_selection.py --mock

# Check output — should be real stocks, NOT inverse ETFs
python3 -c "
import sqlite3
con = sqlite3.connect('data/v2_universe.db')
print('=== TOP 5 LONGS ===')
for r in con.execute('''
    SELECT rank, ticker, direction, final_score, tcn_score, factor_rank, beta
    FROM shortlist_daily WHERE direction='LONG' 
    AND date=(SELECT MAX(date) FROM shortlist_daily)
    ORDER BY rank LIMIT 5
''').fetchall():
    print(r)
print()
print('=== TOP 5 SHORTS ===')
for r in con.execute('''
    SELECT rank, ticker, direction, final_score, tcn_score, factor_rank, beta
    FROM shortlist_daily WHERE direction='SHORT'
    AND date=(SELECT MAX(date) FROM shortlist_daily)
    ORDER BY rank LIMIT 5
''').fetchall():
    print(r)
con.close()
"

# Restart API
kill $(lsof -ti:8080) 2>/dev/null; sleep 1
python3 stages/v2_api_server.py &
sleep 3

# Check API returns 60 candidates
curl -s http://localhost:8080/api/candidates | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'{len(d)} candidates')
longs=[x for x in d if x['direction']=='LONG']
shorts=[x for x in d if x['direction']=='SHORT']
print(f'LONGs: {len(longs)}, SHORTs: {len(shorts)}')
if shorts:
    top=shorts[0]
    print(f'Top SHORT: {top[\"ticker\"]} tcn={top.get(\"tcn_score\",\"?\")} final={top.get(\"final_score\",\"?\")}')
    if float(top.get('tcn_score',0)) > 0.65:
        print('BUG: Top short has HIGH tcn_score — inversion not working!')
    else:
        print('OK: Top short has LOW tcn_score — inversion working')
"
```

## Expected after fix:
- Top LONGs: real stocks with high TCN scores (0.7+) and high factor_rank
- Top SHORTs: real stocks with LOW TCN scores (inverted to high final_score)
- No inverse ETFs (BTCZ, SBIT, TSLQ, MSTZ) in top 10 of either side
- Ranks: 1, 2, 3, 4, 5... sequential
- 60 total candidates (30 LONG + 30 SHORT)

## Step 7: Rebuild and deploy UI
```bash
cd ~/SS/Meridian/ui/signalstack-app
npm run build
npx vercel --prod
```

## What NOT to do:
- DO NOT use the probability-weighted E[r] formula
- DO NOT use the alpha model conviction multiplier
- DO NOT remove beta stripping entirely
- DO NOT change stages 1-4B or 6-7
- DO NOT change the factor engine or TCN model
- Keep the existing side-aware factor percentile direction logic
- Keep the existing beta computation (60-day rolling regression)

## Acceptance Criteria:
- [ ] Blend formula restored: 0.60 * factor_rank + 0.40 * tcn_score for LONGS
- [ ] Option D applied: 0.60 * factor_rank + 0.40 * (1.0 - tcn_score) for SHORTS
- [ ] Direction from sign of residual_alpha (existing logic, unchanged)
- [ ] Ranks are sequential 1, 2, 3... within each side
- [ ] Top shorts have LOW tcn_score (bearish signal)
- [ ] No inverse/leveraged ETFs in top 10
- [ ] API returns alpha, residual_alpha, conviction, tcn_prob fields
- [ ] UI columns work: #, Ticker, Dir, Price, Alpha, Conviction, Sector
- [ ] py_compile passes
- [ ] npm run build passes
- [ ] 60 candidates total
