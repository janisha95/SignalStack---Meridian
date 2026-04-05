# CLAUDE CODE — Investigate Meridian 0 Picks (Evening Report)
# DO NOT FIX anything without consulting Shan first
# Date: Mar 31, 2026

---

## PROBLEM

Evening report shows:
- 📊 Meridian Longs: 0 picks
- 🩻 Meridian Shorts: 0 picks

But S1 has 59 Dual picks + 10 ML Scorer longs. So market data exists.
Meridian pipeline is producing 0 shortlist rows.

This has happened before — suspected cause is the TCN/LGBM scoring
layer producing all-zero probabilities after a pipeline change.

---

## INVESTIGATE (in this order, report ALL output)

### Step 1: Did the Meridian orchestrator run tonight?

```bash
cat ~/SS/logs/evening_$(date +%Y%m%d).log | grep -i "meridian\|v2_orchestrator" | tail -20
ls -la ~/SS/logs/meridian_$(date +%Y%m%d).log 2>/dev/null && tail -30 ~/SS/logs/meridian_$(date +%Y%m%d).log
```

### Step 2: Does the shortlist have any rows for today?

```bash
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT date, COUNT(*) as rows, COUNT(DISTINCT symbol) as symbols
FROM shortlist_daily
WHERE date >= date('now', '-3 days')
GROUP BY date ORDER BY date DESC
"
```

### Step 3: Do predictions exist for today?

```bash
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT date, COUNT(*), AVG(tcn_score), MIN(tcn_score), MAX(tcn_score)
FROM predictions_daily
WHERE date >= date('now', '-3 days')
GROUP BY date ORDER BY date DESC
"
```

### Step 4: What does selection (Stage 5) produce?

```bash
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT date, direction, COUNT(*), AVG(final_score), AVG(factor_rank), AVG(tcn_score)
FROM shortlist_daily
WHERE date >= date('now', '-7 days')
GROUP BY date, direction ORDER BY date DESC
"
```

### Step 5: Are factor scores being computed?

```bash
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT date, COUNT(*), COUNT(DISTINCT symbol)
FROM factor_scores_daily
WHERE date >= date('now', '-3 days')
GROUP BY date ORDER BY date DESC
"
```

### Step 6: Is the TCN model loading?

```bash
ls -la ~/SS/Meridian/models/*.pt 2>/dev/null
ls -la ~/SS/Meridian/models/*.pkl 2>/dev/null
grep -n "model\|load\|tcn\|lgbm\|predict" ~/SS/Meridian/stages/v2_scorer.py | head -20
```

### Step 7: Check the selection formula

```bash
# The current selection uses: final_score = 0.60 * factor_rank + 0.40 * tcn_score
# If tcn_score is all 0.0 or NaN, final_score collapses
grep -n "final_score\|factor_rank\|tcn_score\|0.60\|0.40" ~/SS/Meridian/stages/v2_selection.py | head -15
```

### Step 8: Check if there's a probability threshold filtering everything

```bash
grep -n "threshold\|min_prob\|min_score\|cutoff\|>.*0\." ~/SS/Meridian/stages/v2_selection.py | head -15
```

### Step 9: Check the evening report query

```bash
grep -n "meridian\|shortlist_daily\|predictions_daily" ~/SS/Advance/s1_evening_report_v2.py | head -20
```

### Step 10: Recent orchestrator errors

```bash
grep -i "error\|fail\|exception\|traceback" ~/SS/logs/meridian_$(date +%Y%m%d).log 2>/dev/null | tail -20
grep -i "error\|fail\|exception" ~/SS/Meridian/logs/api_server.log 2>/dev/null | tail -10
```

---

## REPORT TO SHAN

After running ALL 10 steps above, present findings as:

1. **Did the pipeline run?** (yes/no + evidence)
2. **Where in the pipeline did it break?** (factor scores → predictions → selection → shortlist)
3. **Root cause hypothesis** (e.g., TCN model not loading, all predictions 0.0, threshold too high, selection formula producing 0s)
4. **Proposed fix** (describe but DO NOT implement)

Wait for Shan's approval before making any changes.

---

## KNOWN HISTORY

Previous incident (Session 5): probability-weighted expected return model
caused inverse/leveraged ETFs to dominate rankings. Fix was to change
selection formula to `final_score = 0.60 × factor_rank + 0.40 × tcn_score`
with TCN inverted for shorts (`1 - tcn_score`). That fix was committed and
working. This may be a regression or a new issue.
