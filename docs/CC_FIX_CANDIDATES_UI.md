# URGENT FIX: Candidates Page UI — Update Table to Alpha Model

## Problem
The backend (`v2_selection.py`) and API (`v2_api_server.py`) were updated 
to use the new alpha model, but the React candidates page still shows the 
OLD columns: #, Ticker, Dir, Price, Exp Return, Res Alpha, TCN, Final, 
Factor Rank, Beta, Regime, Sector.

The API now returns these fields (check with `curl localhost:8080/api/candidates`):
- `alpha` (the main ranking score — residual alpha from probability-weighted E[r])
- `expected_return` (raw E[r] from TCN probability)
- `conviction` (factor_rank scaled multiplier)
- `tcn_prob` (TCN probability, with `tcn_score` as legacy alias)
- `factor_rank` (cross-sectional percentile)
- `residual_alpha` (same as alpha)
- `beta`, `regime`, `sector`, `price`, `direction`, `rank`
- Legacy aliases: `final_score`, `predicted_return`, `tcn_score` (for backward compat)

## What to do

READ FIRST: ~/SS/Meridian/ui/signalstack-app/app/candidates/candidates-client.tsx
READ ALSO: ~/SS/Meridian/ui/signalstack-app/lib/api.ts
READ ALSO: ~/SS/Meridian/ui/signalstack-app/lib/mock-data.ts

### 1. Update the main table columns

The candidate table must show ONLY these columns in this order:
- # (rank)
- Ticker
- Dir (L green badge / S red badge)
- Price
- Alpha (the residual_alpha value, formatted as percentage like +1.43% or -0.48%, green for positive, red for negative)
- Conviction (a horizontal progress bar showing |alpha| relative to the max |alpha| in today's candidate pool)
- Sector

REMOVE these columns from the main table:
- Exp Return
- Res Alpha (it IS the Alpha column now)
- TCN
- Final (replaced by Alpha)
- Factor Rank
- Beta

### 2. Default sort
- LONGs tab: sort by alpha DESCENDING (highest positive first)
- SHORTs tab: sort by |alpha| DESCENDING (most negative first — show as most negative at top)
- The ACTIVE SORT indicator at bottom should say "alpha" not "finalScore"

### 3. Click-to-expand detail panel
When user clicks a candidate row, the existing slide-out detail panel should show 
these diagnostic fields in a grid ABOVE the TradingView chart:

| Label          | Field from API    | Format          |
|----------------|-------------------|-----------------|
| TCN Probability| tcn_prob          | 0.82            |
| Factor Rank    | factor_rank       | 0.99            |
| Expected Return| expected_return   | +1.46%          |
| Conviction     | conviction        | 0.995           |
| Alpha          | alpha             | +1.43%          |
| Beta           | beta              | 0.17            |
| Regime         | regime            | TRENDING badge  |
| Residual Alpha | residual_alpha    | +1.43%          |

Keep the existing TradingView chart and ticker info card (OPEN, PREV CLOSE, 
VOLUME, DAY HIGH, DAY LOW, MARKET CAP) below the diagnostic grid.

### 4. Conviction bar implementation
```tsx
// Compute max alpha across all candidates for today
const maxAlpha = Math.max(...candidates.map(c => Math.abs(c.alpha || c.residualAlpha || 0)));

// Per candidate:
const barWidth = maxAlpha > 0 ? (Math.abs(candidate.alpha) / maxAlpha) * 100 : 0;
const barColor = candidate.alpha > 0 ? '#1D9E75' : '#E24B4A'; // green for long, red for short

// Render as a simple div with background
<div style={{ width: '100%', height: 6, background: 'rgba(255,255,255,0.1)', borderRadius: 3 }}>
  <div style={{ width: `${barWidth}%`, height: '100%', background: barColor, borderRadius: 3 }} />
</div>
```

### 5. Data mapping
The `lib/api.ts` adapter already maps these fields with fallbacks. 
Check what property names `candidates-client.tsx` actually uses and ensure they match:
- `candidate.alpha` or `candidate.finalScore` → use `alpha` as primary
- `candidate.tcnProb` or `candidate.tcnScore` → use for detail panel
- `candidate.expectedReturn` or `candidate.predictedReturn` → use for detail panel
- `candidate.conviction` → new field for conviction bar

### After changes:
```bash
cd ~/SS/Meridian/ui/signalstack-app
npm run build
# Must pass with zero errors

npm run dev
# Check http://localhost:3000/candidates — should show new columns

# Then deploy:
npx vercel --prod
```

## Acceptance criteria
- [ ] Main table shows ONLY: #, Ticker, Dir, Price, Alpha, Conviction bar, Sector
- [ ] Alpha column: percentage format, green positive, red negative
- [ ] Conviction column: horizontal bar scaled to day's max |alpha|
- [ ] Dir badge: derived visually from alpha sign (positive=L green, negative=S red)
- [ ] Old columns REMOVED from main table: Exp Return, Res Alpha, TCN, Final, Factor Rank, Beta
- [ ] Default sort by alpha (not finalScore)
- [ ] ACTIVE SORT indicator shows "alpha"
- [ ] Click-to-expand detail panel shows: TCN Prob, Factor Rank, Expected Return, Conviction, Alpha, Beta, Regime, Residual Alpha
- [ ] TradingView chart and ticker info card still work in detail panel
- [ ] `npm run build` passes with zero errors
- [ ] Deploy to Vercel succeeds
