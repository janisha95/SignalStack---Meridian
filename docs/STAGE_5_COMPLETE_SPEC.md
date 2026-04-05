# STAGE 5 ALPHA MODEL — COMPLETE IMPLEMENTATION SPEC

**This is the ONLY spec. It replaces all previous specs.**
**Previous specs to IGNORE:** STAGE_5_ALPHA_MODEL_SPEC.md, CC_FIX_CANDIDATES_UI.md, CC_FIX_SELECTION_BUGS.md

**Status:** MUST FIX — production is broken, shorts show positive alpha, ranks are wrong
**Date:** 2026-03-27

---

## Context

Meridian is a 7-stage trading pipeline. Stage 5 (`v2_selection.py`) takes 
TCN classifier scores + factor rankings for ~3,000 US equities and outputs 
a ranked shortlist of 30 LONG + 30 SHORT candidates daily.

The OLD Stage 5 used a hand-written blend: `final_score = 0.60 × factor_rank + 0.40 × tcn_score`
with direction assigned separately via side-aware factor percentiles.

The NEW Stage 5 uses a probability-weighted expected return where direction 
comes from the SIGN of the alpha score. No hand-written weights. No separate 
direction logic.

A partial implementation was attempted but BROKE PRODUCTION:
- Shorts still show positive alpha (direction still from old logic)
- Rank numbers are from old ordering (24, 18, 27... instead of 1, 2, 3...)
- New DB columns (alpha, expected_return, conviction) were added but not populated
- UI was updated to show new columns but backend sends wrong data

---

## Files to read BEFORE making any changes

```
~/SS/Meridian/stages/v2_selection.py        ← PRIMARY TARGET
~/SS/Meridian/stages/v2_api_server.py       ← API layer
~/SS/Meridian/stages/tcn_scorer.py          ← TCN scorer (DO NOT MODIFY)
~/SS/Meridian/stages/v2_risk_filters.py     ← Stage 6, consumes shortlist (check backward compat)
~/SS/Meridian/ui/signalstack-app/lib/api.ts ← Frontend API adapter
~/SS/Meridian/ui/signalstack-app/app/candidates/candidates-client.tsx ← Candidates table
```

---

## Part 1: The Alpha Formula

The TCN was trained with TBM labels: +2% = WIN (label=1), -1% = LOSE (label=0).
Its output is P(WIN), a probability between 0 and 1.

Convert this probability to an expected return:
```
E[r] = tcn_prob × 0.02 + (1 - tcn_prob) × (-0.01)
```

This is mathematically derived from the training objective. Not a hand-written weight.

Breakeven: p = 1/3 = 0.333. Above → positive E[r] → LONG. Below → negative E[r] → SHORT.

Full pipeline per ticker:
```
Step 1: e_r = tcn_prob * 0.02 + (1 - tcn_prob) * (-0.01)
Step 2: conviction = 0.5 + 0.5 * factor_rank
Step 3: alpha = e_r * conviction
Step 4: spy_e_r = spy_tcn_prob * 0.02 + (1 - spy_tcn_prob) * (-0.01)
        spy_conviction = 0.5 + 0.5 * spy_factor_rank
        spy_alpha = spy_e_r * spy_conviction
Step 5: residual_alpha = alpha - (beta * spy_alpha)
Step 6: direction = "LONG" if residual_alpha > 0 else "SHORT"
```

CRITICAL: Direction is determined in Step 6 AFTER alpha is computed.
Direction is NOT determined before alpha. Direction is NOT from factor percentiles.
Direction is NOT from any separate logic. It comes from the SIGN of residual_alpha. Period.

Constants:
```python
TBM_WIN_RETURN = 0.02
TBM_LOSE_RETURN = -0.01
CONVICTION_FLOOR = 0.5
MIN_ALPHA_THRESHOLD = 0.001
```

---

## Part 2: Backend changes (v2_selection.py)

### What to ADD:

```python
TBM_WIN_RETURN = 0.02
TBM_LOSE_RETURN = -0.01
CONVICTION_FLOOR = 0.5
MIN_ALPHA_THRESHOLD = 0.001

def compute_alpha(tcn_prob, factor_rank, beta, spy_tcn_prob, spy_factor_rank):
    """Compute alpha from TCN probability and factor rank.
    
    Direction comes from the SIGN of residual_alpha.
    No separate direction logic. No side-aware percentiles.
    """
    e_r = tcn_prob * TBM_WIN_RETURN + (1 - tcn_prob) * TBM_LOSE_RETURN
    conviction = CONVICTION_FLOOR + (1 - CONVICTION_FLOOR) * factor_rank
    alpha = e_r * conviction
    
    spy_e_r = spy_tcn_prob * TBM_WIN_RETURN + (1 - spy_tcn_prob) * TBM_LOSE_RETURN
    spy_conviction = CONVICTION_FLOOR + (1 - CONVICTION_FLOOR) * spy_factor_rank
    spy_alpha = spy_e_r * spy_conviction
    
    residual_alpha = alpha - (beta * spy_alpha)
    direction = "LONG" if residual_alpha > 0 else "SHORT"
    
    return {
        "expected_return": round(e_r, 6),
        "conviction": round(conviction, 4),
        "alpha": round(alpha, 6),
        "residual_alpha": round(residual_alpha, 6),
        "direction": direction,
    }
```

### What to CHANGE in the main selection flow:

The current code likely does something like:
1. Split tickers into LONG/SHORT pools based on factor percentiles
2. Rank within each pool by final_score = 0.60 * factor_rank + 0.40 * tcn_score
3. Maybe compute alpha as an additional column

This is WRONG. Replace the entire scoring+ranking+direction flow with:

```python
# 1. Get SPY's TCN prob and factor rank
spy_tcn_prob = tcn_scores.get("SPY", 0.5)
spy_factor_rank = factor_ranks.get("SPY", 0.5)

# 2. Compute alpha for ALL tickers (do NOT pre-split by direction)
scored = []
for ticker in all_tickers:
    tcn_prob = tcn_scores.get(ticker, 0.5)  # fallback to neutral
    factor_rank = factor_ranks.get(ticker, 0.5)
    beta = betas.get(ticker, 1.0)
    
    result = compute_alpha(tcn_prob, factor_rank, beta, spy_tcn_prob, spy_factor_rank)
    result["ticker"] = ticker
    result["tcn_score"] = tcn_prob       # keep for diagnostics
    result["factor_rank"] = factor_rank  # keep for diagnostics
    result["beta"] = beta
    result["regime"] = regimes.get(ticker, "UNKNOWN")
    result["sector"] = sectors.get(ticker, "UNKNOWN")
    result["price"] = prices.get(ticker, 0.0)
    scored.append(result)

# 3. Filter out near-zero alpha (noise)
scored = [t for t in scored if abs(t["residual_alpha"]) > MIN_ALPHA_THRESHOLD]

# 4. Split by direction (which was determined by sign of residual_alpha)
longs = [t for t in scored if t["direction"] == "LONG"]
shorts = [t for t in scored if t["direction"] == "SHORT"]

# 5. Rank: LONGs by residual_alpha DESCENDING (highest positive = rank 1)
longs.sort(key=lambda x: x["residual_alpha"], reverse=True)
for i, t in enumerate(longs[:top_n]):
    t["rank"] = i + 1

# 6. Rank: SHORTs by residual_alpha ASCENDING (most negative = rank 1)
shorts.sort(key=lambda x: x["residual_alpha"])
for i, t in enumerate(shorts[:top_n]):
    t["rank"] = i + 1

# 7. Combine for DB write
shortlist = longs[:top_n] + shorts[:top_n]
```

### What to REMOVE:
- Any `final_score = X * factor_rank + Y * tcn_score` blend formula
- Any side-aware factor percentile direction assignment
- Any code that pre-splits tickers into LONG/SHORT before computing scores
- Any code that sets direction based on anything other than the sign of residual_alpha

### Fallback when TCN model is missing:
```python
# tcn_prob = 0.5 for all tickers
# e_r = 0.5 * 0.02 + 0.5 * (-0.01) = +0.005
# All tickers get slightly positive E[r] → all LONG
# factor_rank alone drives conviction scaling
# This is acceptable as a degraded state
```

### DB schema (shortlist_daily):

The table needs these columns. If any are missing, add them with ALTER TABLE:
```sql
ALTER TABLE shortlist_daily ADD COLUMN expected_return REAL;
ALTER TABLE shortlist_daily ADD COLUMN conviction REAL;
ALTER TABLE shortlist_daily ADD COLUMN alpha REAL;
```

Keep existing columns: date, ticker, direction, predicted_return, beta, 
market_component, residual_alpha, rank, regime, sector, price, 
top_shap_factors, factor_rank, tcn_score, final_score.

When writing new rows, set:
- expected_return = the E[r] value
- conviction = the conviction multiplier
- alpha = the residual_alpha value (they are the same in current pipeline)
- predicted_return = expected_return (backward compat for Stage 6)
- final_score = abs(residual_alpha) (backward compat for Stage 6)
- direction = from sign of residual_alpha
- rank = 1, 2, 3... based on new alpha ordering

The backward compat fields (predicted_return, final_score) ensure Stage 6 
risk filters don't break. Stage 6 reads predicted_return for sizing.

---

## Part 3: API changes (v2_api_server.py)

The `/api/candidates` endpoint reads from shortlist_daily and returns JSON.

Update the SQL query and normalize function to include:
- `alpha` (the residual_alpha value)
- `expected_return` (the E[r] value)  
- `conviction` (the multiplier)
- `tcn_prob` (the tcn_score value, renamed for clarity)

Keep legacy field names as aliases so the UI doesn't break:
- `final_score` = abs(residual_alpha)
- `predicted_return` = expected_return
- `tcn_score` = tcn_prob value

The normalize function `_normalize_candidate_rows()` should map:
```python
{
    "ticker": row["ticker"],
    "direction": row["direction"],
    "rank": row["rank"],
    "price": row["price"],
    "alpha": row.get("alpha") or row.get("residual_alpha", 0),
    "expected_return": row.get("expected_return") or row.get("predicted_return", 0),
    "conviction": row.get("conviction", 0.75),
    "residual_alpha": row.get("residual_alpha", 0),
    "tcn_prob": row.get("tcn_score", 0.5),
    "factor_rank": row.get("factor_rank", 0.5),
    "beta": row.get("beta", 1.0),
    "regime": row.get("regime", "UNKNOWN"),
    "sector": row.get("sector", "UNKNOWN"),
    # Legacy aliases for backward compat
    "tcn_score": row.get("tcn_score", 0.5),
    "final_score": abs(row.get("residual_alpha", 0)),
    "predicted_return": row.get("expected_return") or row.get("predicted_return", 0),
}
```

---

## Part 4: UI changes (React — candidates-client.tsx)

### Main table columns (7 total):
| Column | Field | Format |
|--------|-------|--------|
| # | rank | Integer 1, 2, 3... |
| Ticker | ticker | Text, clickable |
| Dir | direction | L (green badge) / S (red badge) |
| Price | price | $XX.XX |
| Alpha | alpha | +X.XX% green / -X.XX% red |
| Conviction | alpha | Horizontal bar, width = \|alpha\| / max(\|alpha\|) × 100% |
| Sector | sector | Text |

### REMOVED from main table:
- Exp Return column
- Res Alpha column (it IS the Alpha column now)
- TCN column
- Final column
- Factor Rank column
- Beta column

### Default sort:
- LONG tab: alpha descending (ranks already 1,2,3 from backend)
- SHORT tab: alpha ascending (most negative first, ranks already 1,2,3 from backend)
- Footer sort label: "alpha"

### Conviction bar:
```tsx
const maxAlpha = Math.max(...candidates.map(c => Math.abs(c.alpha || 0)), 0.001);
const barPct = (Math.abs(candidate.alpha || 0) / maxAlpha) * 100;
const barColor = candidate.direction === 'LONG' ? '#1D9E75' : '#E24B4A';
```

### Click-to-expand detail panel:
When a row is clicked, show these fields in a grid ABOVE the TradingView chart:
- TCN Probability: tcn_prob (e.g. 0.82)
- Factor Rank: factor_rank (e.g. 0.99)
- Expected Return: expected_return (e.g. +1.46%)
- Conviction: conviction (e.g. 0.995)
- Alpha: alpha (e.g. +1.43%)
- Beta: beta (e.g. 0.17)
- Regime: regime (e.g. TRENDING badge)
- Residual Alpha: residual_alpha (e.g. +1.43%)

Keep existing TradingView chart and ticker info card below.

### Data mapping in lib/api.ts:
The adaptCandidates() function should read:
- alpha: response.alpha || response.residual_alpha || response.final_score || 0
- tcnProb: response.tcn_prob || response.tcn_score || 0.5
- expectedReturn: response.expected_return || response.predicted_return || 0
- conviction: response.conviction || 0.75
- factorRank: response.factor_rank || 0.5

---

## Part 5: Verification

### After backend fix:
```bash
cd ~/SS/Meridian

# 1. Compile check
python3 -c "import ast; ast.parse(open('stages/v2_selection.py').read()); print('OK')"
python3 -c "import ast; ast.parse(open('stages/v2_api_server.py').read()); print('OK')"

# 2. Dry run
python3 stages/v2_selection.py --mock --dry-run 2>&1 | head -30

# 3. Real run (writes to DB)
python3 stages/v2_selection.py --mock

# 4. Verify DB output
python3 -c "
import sqlite3
con = sqlite3.connect('data/v2_universe.db')
print('=== TOP 5 LONGS ===')
for r in con.execute('''
    SELECT rank, ticker, direction, residual_alpha, alpha, expected_return, conviction 
    FROM shortlist_daily WHERE direction='LONG' 
    ORDER BY rank LIMIT 5
''').fetchall():
    print(r)
print()
print('=== TOP 5 SHORTS ===')
for r in con.execute('''
    SELECT rank, ticker, direction, residual_alpha, alpha, expected_return, conviction 
    FROM shortlist_daily WHERE direction='SHORT' 
    ORDER BY rank LIMIT 5
''').fetchall():
    print(r)
con.close()
"

# EXPECTED:
# - LONG ranks: 1,2,3,4,5 with POSITIVE residual_alpha, descending
# - SHORT ranks: 1,2,3,4,5 with NEGATIVE residual_alpha, most negative first
# - NO short with positive residual_alpha
# - NO long with negative residual_alpha
# - expected_return values around -0.01 to +0.02
# - conviction values between 0.5 and 1.0

# 5. Verify API
curl -s http://localhost:8080/api/candidates | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'{len(data)} candidates')
if data:
    longs = [d for d in data if d.get('direction') == 'LONG']
    shorts = [d for d in data if d.get('direction') == 'SHORT']
    print(f'LONGs: {len(longs)}, SHORTs: {len(shorts)}')
    if longs:
        print(f'Top LONG: {longs[0][\"ticker\"]} alpha={longs[0].get(\"alpha\",\"?\")}')
    if shorts:
        print(f'Top SHORT: {shorts[0][\"ticker\"]} alpha={shorts[0].get(\"alpha\",\"?\")}')
        if shorts[0].get('alpha', 0) > 0:
            print('BUG: Top short has positive alpha!')
"
```

### After UI fix:
```bash
cd ~/SS/Meridian/ui/signalstack-app
npm run build    # MUST pass with zero errors
npm run dev      # Check http://localhost:3000/candidates

# Then deploy:
npx vercel --prod
```

### Visual verification on deployed site:
- [ ] LONG tab: ranks are 1, 2, 3, 4, 5... (not 24, 18, 27...)
- [ ] LONG tab: all alpha values are POSITIVE (green)
- [ ] SHORT tab: all alpha values are NEGATIVE (red)
- [ ] SHORT tab: most negative alpha is rank 1 at the top
- [ ] NO short candidate has positive alpha
- [ ] NO long candidate has negative alpha
- [ ] Main table has exactly 7 columns: #, Ticker, Dir, Price, Alpha, Conviction, Sector
- [ ] Conviction bar scales correctly (longest bar = highest |alpha|)
- [ ] Click on a row shows detail panel with TCN prob, factor rank, E[r], conviction, alpha, beta, regime

---

## Part 6: What NOT to change

- DO NOT modify stages 1-4B (cache, prefilter, factor engine, TCN scorer)
- DO NOT modify stage 6 (risk filters) — it reads predicted_return and final_score via backward compat aliases
- DO NOT modify stage 7 (orchestrator) 
- DO NOT modify the TCN model or training code
- DO NOT modify the factor engine or factor registry
- DO NOT create any new files — only modify existing files

---

## Acceptance Criteria (ALL must pass)

### Backend:
- [ ] `compute_alpha()` function exists in v2_selection.py
- [ ] Direction is determined by sign of residual_alpha ONLY
- [ ] No hand-written blend weights (no 0.60/0.40 formula)
- [ ] No side-aware factor percentile direction assignment
- [ ] Tickers are NOT pre-split into LONG/SHORT before alpha computation
- [ ] LONGs: all have positive residual_alpha, ranked 1,2,3... descending
- [ ] SHORTs: all have NEGATIVE residual_alpha, ranked 1,2,3... ascending
- [ ] Fallback mode works (tcn_prob=0.5 when model missing)
- [ ] Backward compat: predicted_return and final_score populated for Stage 6
- [ ] py_compile passes on v2_selection.py and v2_api_server.py

### API:
- [ ] /api/candidates returns alpha, expected_return, conviction, tcn_prob fields
- [ ] /api/candidates returns legacy aliases (final_score, predicted_return, tcn_score)
- [ ] Restart API server, verify with curl

### UI:
- [ ] Main table: 7 columns only (#, Ticker, Dir, Price, Alpha, Conviction, Sector)
- [ ] Alpha: percentage format, green positive, red negative
- [ ] Conviction: horizontal bar scaled to day's max |alpha|
- [ ] Ranks: sequential 1,2,3... (not stale old ranks)
- [ ] Click-to-expand: diagnostic grid with TCN prob, factor rank, E[r], etc.
- [ ] npm run build passes
- [ ] Deployed to Vercel
