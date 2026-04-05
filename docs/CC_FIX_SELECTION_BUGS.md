# URGENT FIX: v2_selection.py — Two Critical Bugs

## READ FIRST
~/SS/Meridian/docs/STAGE_5_ALPHA_MODEL_SPEC.md
~/SS/Meridian/stages/v2_selection.py

## Bug 1: Numbering is wrong on LONG tab
The # column shows 24, 18, 27, 20, 21... instead of 1, 2, 3, 4, 5...
The `rank` column in shortlist_daily is stale from the old 60/40 blend.
After computing alpha and residual_alpha, the rank must be RE-ASSIGNED 
based on the new alpha ordering:
- LONGs: sort by residual_alpha DESCENDING, then rank = 1, 2, 3...
- SHORTs: sort by residual_alpha ASCENDING (most negative first), then rank = 1, 2, 3...

## Bug 2: SHORT candidates have POSITIVE alpha
The SHORT tab shows tickers like OUST with alpha=+0.05%, PTIR with +0.02%.
If alpha is positive, the ticker should be LONG, not SHORT.
This means DIRECTION IS STILL BEING SET BY THE OLD LOGIC (side-aware factor 
percentiles) instead of from the sign of residual_alpha.

## Root Cause
The previous Claude Code session likely ADDED the new alpha columns alongside 
the old direction/ranking logic instead of REPLACING it. The old code probably 
still does:
1. Separate LONG/SHORT pools based on factor percentiles
2. Ranks within each pool by final_score
3. Then computes alpha as an additional column

## Required Fix
The alpha pipeline must REPLACE the old logic entirely:

```python
# STEP 1: Compute alpha for ALL tickers (not pre-split by direction)
for ticker in all_tickers:
    result = compute_alpha(tcn_prob, factor_rank, beta, spy_tcn_prob, spy_factor_rank)
    # result has: expected_return, conviction, alpha, residual_alpha, direction

# STEP 2: Direction comes FROM the sign of residual_alpha
#   residual_alpha > 0  → LONG
#   residual_alpha < 0  → SHORT
#   DO NOT use side-aware factor percentiles for direction
#   DO NOT pre-split into LONG/SHORT pools before computing alpha

# STEP 3: Split AFTER direction is determined
longs = [t for t in scored if t["direction"] == "LONG" 
         and abs(t["residual_alpha"]) > MIN_ALPHA_THRESHOLD]
shorts = [t for t in scored if t["direction"] == "SHORT" 
          and abs(t["residual_alpha"]) > MIN_ALPHA_THRESHOLD]

# STEP 4: Rank AFTER split
longs.sort(key=lambda x: x["residual_alpha"], reverse=True)
for i, t in enumerate(longs[:top_n]):
    t["rank"] = i + 1  # 1, 2, 3... NOT the old rank

shorts.sort(key=lambda x: x["residual_alpha"])  # most negative first
for i, t in enumerate(shorts[:top_n]):
    t["rank"] = i + 1  # 1, 2, 3... NOT the old rank
```

## Key Constants
```python
TBM_WIN_RETURN = 0.02
TBM_LOSE_RETURN = -0.01
CONVICTION_FLOOR = 0.5
MIN_ALPHA_THRESHOLD = 0.001
```

## Alpha Formula (per ticker)
```python
e_r = tcn_prob * 0.02 + (1 - tcn_prob) * (-0.01)
conviction = 0.5 + 0.5 * factor_rank
alpha = e_r * conviction
spy_alpha = (spy_tcn_prob * 0.02 + (1 - spy_tcn_prob) * (-0.01)) * (0.5 + 0.5 * spy_factor_rank)
residual_alpha = alpha - (beta * spy_alpha)
direction = "LONG" if residual_alpha > 0 else "SHORT"
```

## What to look for in the existing code
Search v2_selection.py for:
- Any place where direction is set BEFORE alpha is computed → WRONG
- Any place where tickers are split into LONG/SHORT pools before alpha → WRONG
- Any place where rank comes from the old final_score ordering → WRONG
- Any "side-aware factor percentile" logic → this should NOT determine direction anymore

## Verification
After fix, run:
```bash
python3 stages/v2_selection.py --mock --dry-run 2>&1 | head -40
```

Expected output:
- LONGs should have POSITIVE residual_alpha, ranked 1,2,3... descending
- SHORTs should have NEGATIVE residual_alpha, ranked 1,2,3... ascending (most negative = rank 1)
- NO short should have positive alpha
- NO long should have negative alpha

Then run for real:
```bash
python3 stages/v2_selection.py --mock
```

Then verify DB:
```bash
python3 -c "
import sqlite3
con = sqlite3.connect('data/v2_universe.db')
print('=== TOP 5 LONGS ===')
for r in con.execute('SELECT rank, ticker, direction, residual_alpha, alpha FROM shortlist_daily WHERE direction=\"LONG\" ORDER BY rank LIMIT 5').fetchall():
    print(r)
print('=== TOP 5 SHORTS ===')
for r in con.execute('SELECT rank, ticker, direction, residual_alpha, alpha FROM shortlist_daily WHERE direction=\"SHORT\" ORDER BY rank LIMIT 5').fetchall():
    print(r)
con.close()
"
```

Expected:
- LONG ranks: 1,2,3,4,5 with positive residual_alpha, descending
- SHORT ranks: 1,2,3,4,5 with NEGATIVE residual_alpha, most negative first

## After backend fix, redeploy UI:
```bash
cd ~/SS/Meridian/ui/signalstack-app
npm run build && npx vercel --prod
```

## Acceptance Criteria
- [ ] ALL shorts have negative residual_alpha (no positive alpha shorts)
- [ ] ALL longs have positive residual_alpha (no negative alpha longs)  
- [ ] Rank column is 1,2,3... based on alpha ordering, not old final_score
- [ ] Direction determined by sign of residual_alpha, not factor percentiles
- [ ] py_compile passes
- [ ] Dry run shows correct ranking and direction
