# URGENT: Restore Original UI Columns — candidates-client.tsx

## Context
The backend was rolled back to the 60/40 blend with Option D.
But the UI still shows the NEW simplified columns (#, Ticker, Dir, Price, Alpha, Conviction, Sector).
This is wrong. The UI must match the backend. Rollback means EVERYTHING goes back.

## READ FIRST
~/SS/Meridian/ui/signalstack-app/app/candidates/candidates-client.tsx

## What the main table columns MUST be (the ORIGINAL layout):

| # | Ticker | Dir | Price | Exp Return | Res Alpha | TCN | Final ▼ | Factor Rank | Beta | Regime | Sector |

These are the columns that were working before the alpha model changes.

## What to do

1. Restore the main candidate table to show ALL 12 columns:
   - # (rank)
   - Ticker (clickable, opens detail panel)
   - Dir (L green / S red badge)
   - Price ($XX.XX)
   - Exp Return (predicted_return as percentage, green/red)
   - Res Alpha (residual_alpha as percentage, green/red)
   - TCN (tcn_score as decimal, e.g. 0.82)
   - Final (final_score as decimal with bar, sorted descending by default)
   - Factor Rank (factor_rank as decimal)
   - Beta (beta as decimal, can be negative)
   - Regime (TRENDING/CHOPPY/VOLATILE badge)
   - Sector (text)

2. REMOVE the "Conviction" progress bar column — that was from the new alpha model UI.

3. Default sort: Final score DESCENDING for both LONG and SHORT tabs.
   The footer sort indicator should show "finalScore".

4. Keep the click-to-expand detail panel with TradingView chart and ticker info.
   The "ALPHA MODEL DIAGNOSTICS" section in the detail panel can stay if it's 
   showing useful data (TCN prob, factor rank, exp return, conviction, alpha, 
   beta, regime, res alpha). Or remove it and keep just the TradingView chart 
   + ticker info card that was there originally. Either way is fine — the main 
   table columns are what matters.

5. Data mapping in lib/api.ts:
   The API returns these fields. Make sure the table reads them correctly:
   - predicted_return → Exp Return column
   - residual_alpha → Res Alpha column  
   - tcn_score or tcn_prob → TCN column
   - final_score or conviction → Final column
   - factor_rank → Factor Rank column
   - beta → Beta column
   - regime → Regime column
   - sector → Sector column

## After changes:
```bash
cd ~/SS/Meridian/ui/signalstack-app
npm run build    # MUST pass with zero errors
npx vercel --prod
```

## Verify on https://signalstack-app.vercel.app:
- [ ] 12 columns visible: #, Ticker, Dir, Price, Exp Return, Res Alpha, TCN, Final, Factor Rank, Beta, Regime, Sector
- [ ] No "Conviction" bar column
- [ ] Final column has sort indicator, sorted descending
- [ ] LONG tab: 30 candidates, real stocks
- [ ] SHORT tab: 30 candidates, shorts have LOW tcn scores
- [ ] Click ticker opens detail panel with TradingView chart
