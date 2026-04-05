# Quick Fix: Invert TCN/LGBM Scores for SHORT Candidates (Option D)

## Problem
SHORT candidates have high TCN scores (e.g., PICK has TCN=0.95) because 
the TCN was trained to predict bullishness. A high TCN = bullish, which 
contradicts the SHORT direction assignment.

## Fix
In ~/SS/Meridian/stages/v2_selection.py, find where final_score is 
computed for shorts. Currently it's:

```python
shorts_base["final_score"] = (
    FACTOR_BLEND * shorts_base["factor_rank"]
    + TCN_BLEND_FACTOR * shorts_base["tcn_score"]
    + LGBM_BLEND_FACTOR * shorts_base["lgbm_score"]
)
```

Change to INVERT tcn_score and lgbm_score for shorts:

```python
shorts_base["final_score"] = (
    FACTOR_BLEND * shorts_base["factor_rank"]
    + TCN_BLEND_FACTOR * (1.0 - shorts_base["tcn_score"])
    + LGBM_BLEND_FACTOR * (1.0 - shorts_base["lgbm_score"])
)
```

This means:
- TCN=0.95 (bullish) → 1-0.95 = 0.05 for short scoring → terrible short
- TCN=0.10 (bearish) → 1-0.10 = 0.90 for short scoring → great short
- LGBM follows the same logic

Factor_rank is NOT inverted because it's already side-aware 
(computed separately for the short pool).

## After Fix
- PICK (TCN=0.95) will get short_tcn=0.05, cratering its final_score
- Tickers with LOW TCN (bearish signal) will rise to the top of shorts
- LONGs are unchanged

## Also Fix: Short Sort Direction
In candidates-client.tsx, SHORT tab should sort by final_score 
DESCENDING (highest first = most confident short picks), same as longs.

## Verify
```bash
cd ~/SS/Meridian
python3 stages/v2_orchestrator.py
# Then check: no SHORT should have tcn_score > 0.65 AND high final_score
curl -s http://localhost:8080/api/candidates | python3 -c "
import json,sys; d=json.load(sys.stdin)
shorts = [c for c in d if c['direction']=='SHORT']
for s in sorted(shorts, key=lambda x: x.get('final_score',0), reverse=True)[:5]:
    print(f\"{s['ticker']:6s} tcn={s.get('tcn_score',0):.2f} final={s.get('final_score',0):.2f}\")
"
# Top shorts should now have LOW tcn_score (bearish)
```

py_compile after.
