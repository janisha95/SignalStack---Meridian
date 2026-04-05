# DEEP CODE AUDIT — Meridian Stage 4 + 5 (Investigate Only, No Changes)

## CONTEXT

Meridian is a daily US equity swing trading system. The pipeline runs Stages 1-7 every evening at 5 PM ET. Stages 4 and 5 have been broken or degraded since LGBM models were added alongside the existing TCN model. A previous Claude Code session applied a "quick fix" (filling structurally absent features with 0.5 neutral) that may be masking deeper issues.

**There is a TCN v2 model with IC=0.105 (3.4× better than v1 at IC=0.031) that is NOT wired into production.** This is the highest priority item to understand and fix.

## YOUR TASK

**INVESTIGATE ONLY. Do NOT modify any files.** Report all findings to me and I will decide what to fix.

Run every diagnostic below. Print ALL output. Then write a summary of what's broken and what needs to change.

---

## PHASE 1: File Inventory

```bash
echo "=== MODEL FILES ==="
ls -la ~/SS/Meridian/models/
ls -la ~/SS/Meridian/models/tcn_pass_v1/ 2>/dev/null
ls -la ~/SS/Meridian/models/tcn_v2*/ 2>/dev/null
find ~/SS/Meridian/models/ -name "*.pt" -o -name "*.pkl" -o -name "*.txt" -o -name "*.json" | sort

echo ""
echo "=== STAGE FILES ==="
ls -la ~/SS/Meridian/stages/tcn_scorer.py
ls -la ~/SS/Meridian/stages/v2_selection.py
ls -la ~/SS/Meridian/stages/v2_orchestrator.py
ls -la ~/SS/Meridian/stages/v2_model_trainer.py 2>/dev/null
ls -la ~/SS/Meridian/stages/v2_factor_engine.py

echo ""
echo "=== GIT LOG (last 20 commits) ==="
cd ~/SS/Meridian && git log --oneline -20
```

---

## PHASE 2: Which TCN Model Is Actually Loaded?

```bash
echo "=== TCN SCORER — What model path does it load? ==="
grep -n "model_dir\|model_path\|load_state\|model.pt\|config.json\|tcn_pass\|tcn_v2" ~/SS/Meridian/stages/tcn_scorer.py

echo ""
echo "=== TCN SCORER — What features does it expect? ==="
grep -n "FEATURES\|features\|feature_list\|TCN_FEATURES\|19\|feature_names" ~/SS/Meridian/stages/tcn_scorer.py | head -20

echo ""
echo "=== TCN CONFIG — What does the model config say? ==="
cat ~/SS/Meridian/models/tcn_pass_v1/config.json 2>/dev/null
find ~/SS/Meridian/models/ -name "config.json" -exec echo "--- {} ---" \; -exec cat {} \;

echo ""
echo "=== MODEL FILE SIZES ==="
find ~/SS/Meridian/models/ -name "*.pt" -exec ls -la {} \;
```

**KEY QUESTION:** Is the TCN v2 model (IC=0.105, trained on A100 with 5 years of data) stored somewhere on disk? If so, where? If not, it may need to be re-downloaded from Vast.ai or Google Drive.

---

## PHASE 3: The "Structural NaN" Fix — Is It Sound?

The previous CC session filled 7 features with 0.5 neutral because they were >90% NaN in factor_history. This means TCN is running on 12 real features + 7 dummy features.

```bash
echo "=== STRUCTURAL NAN FIX — exact code ==="
grep -n -A 10 "structural\|structurally\|absent\|0\.5\|neutral\|fill\|backfill" ~/SS/Meridian/stages/tcn_scorer.py

echo ""
echo "=== FACTOR HISTORY — which features have data for last 64 dates? ==="
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT date, COUNT(*) as rows,
  SUM(CASE WHEN momentum_impulse IS NOT NULL THEN 1 ELSE 0 END) as has_momentum_impulse,
  SUM(CASE WHEN volume_flow_direction IS NOT NULL THEN 1 ELSE 0 END) as has_volume_flow_dir,
  SUM(CASE WHEN effort_vs_result IS NOT NULL THEN 1 ELSE 0 END) as has_effort_vs_result,
  SUM(CASE WHEN volatility_acceleration IS NOT NULL THEN 1 ELSE 0 END) as has_vol_accel,
  SUM(CASE WHEN wick_rejection IS NOT NULL THEN 1 ELSE 0 END) as has_wick_rejection,
  SUM(CASE WHEN rollover_strength IS NOT NULL THEN 1 ELSE 0 END) as has_rollover,
  SUM(CASE WHEN rs_momentum IS NOT NULL THEN 1 ELSE 0 END) as has_rs_momentum
FROM factor_history 
WHERE date >= date('now', '-90 days')
GROUP BY date
ORDER BY date DESC
LIMIT 10
"

echo ""
echo "=== How many dates have ALL 19 TCN features populated? ==="
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT COUNT(DISTINCT date) as total_dates,
  SUM(CASE WHEN has_all = 19 THEN 1 ELSE 0 END) as complete_dates
FROM (
  SELECT date,
    (CASE WHEN adx IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN bb_position IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN dist_from_ma20_atr IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN rs_vs_spy_10d IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN volume_participation IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN momentum_acceleration IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN volatility_rank IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN wyckoff_phase IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN ma_alignment IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN leadership_score IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN setup_score IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN damage_depth IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN volume_climax IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN rs_vs_spy_20d IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN ma_death_cross_proximity IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN downside_volume_dominance IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN phase_confidence IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN directional_conviction IS NOT NULL THEN 1 ELSE 0 END) +
    (CASE WHEN vix_regime IS NOT NULL THEN 1 ELSE 0 END) as has_all
  FROM factor_history
  GROUP BY date
)
"
```

**KEY QUESTION:** Are the 7 "structurally absent" features actually absent because the factor engine doesn't compute them? Or because factor_history backfill was never run? The fix (filling with 0.5) is a band-aid — the real fix is to either backfill the history or accept that TCN only has 12/19 features.

---

## PHASE 4: How Does Stage 4 Actually Work?

Stage 4 was originally just TCN scoring. Then LGBM was added. What is the actual flow now?

```bash
echo "=== ORCHESTRATOR — Stage 4 call chain ==="
grep -n -A 15 "stage.*4\|Stage 4\|ml.*scor\|tcn_scor\|lgbm\|real.ml\|mock.ml\|predictions" ~/SS/Meridian/stages/v2_orchestrator.py | head -60

echo ""
echo "=== Does orchestrator call TCN scorer separately from LGBM? ==="
grep -n "tcn_scorer\|import.*tcn\|from.*tcn\|lgbm.*predict\|predictions_daily" ~/SS/Meridian/stages/v2_orchestrator.py

echo ""
echo "=== What does --real-ml actually do? ==="
grep -n "real.ml\|real_ml\|mock_ml\|mock.ml" ~/SS/Meridian/stages/v2_orchestrator.py

echo ""
echo "=== What writes to predictions_daily? ==="
grep -rn "predictions_daily" ~/SS/Meridian/stages/*.py | head -20

echo ""
echo "=== Current predictions in DB ==="
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT date, COUNT(*) as rows, 
  AVG(predicted_return) as avg_pred,
  MIN(predicted_return) as min_pred,
  MAX(predicted_return) as max_pred
FROM predictions_daily
WHERE date >= date('now', '-3 days')
GROUP BY date
ORDER BY date DESC
"

echo ""
echo "=== Current TCN scores in DB ==="
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT date, COUNT(*) as rows,
  AVG(tcn_score) as avg_tcn,
  MIN(tcn_score) as min_tcn,
  MAX(tcn_score) as max_tcn,
  SUM(CASE WHEN tcn_score = 0.5 THEN 1 ELSE 0 END) as flat_05
FROM predictions_daily
WHERE date >= date('now', '-3 days')
GROUP BY date
ORDER BY date DESC
"
```

**KEY QUESTIONS:**
1. Does --real-ml trigger both LGBM AND TCN scoring? Or just LGBM?
2. Where do tcn_score values come from in the DB? From tcn_scorer.py writing directly? Or from orchestrator merging?
3. When LGBM was added, did it REPLACE the TCN call or sit alongside it?

---

## PHASE 5: Stage 5 Selection — What Does It Actually Read?

```bash
echo "=== SELECTION — Full file head (first 80 lines) ==="
head -80 ~/SS/Meridian/stages/v2_selection.py

echo ""
echo "=== SELECTION — Where does it get tcn_score? ==="
grep -n "tcn_score\|tcn\|factor_rank\|final_score\|blend\|0\.60\|0\.40\|residual_alpha" ~/SS/Meridian/stages/v2_selection.py

echo ""
echo "=== SELECTION — Where does it get LGBM predictions? ==="
grep -n "lgbm\|predicted_return\|predictions_daily\|predict" ~/SS/Meridian/stages/v2_selection.py

echo ""
echo "=== SELECTION — What's the actual blend formula in code? ==="
grep -n -B 2 -A 5 "final_score\|blend\|0\.6\|0\.4\|score.*=" ~/SS/Meridian/stages/v2_selection.py

echo ""
echo "=== Today's shortlist — are TCN scores real or 0.5? ==="
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT direction, ticker, 
  ROUND(tcn_score, 4) as tcn, 
  ROUND(factor_rank, 4) as fr,
  ROUND(final_score, 4) as final
FROM shortlist_daily 
WHERE date = (SELECT MAX(date) FROM shortlist_daily)
ORDER BY direction, final_score DESC
LIMIT 20
"
```

**KEY QUESTION:** Is Stage 5 using the CORRECT blend formula (0.60 × factor_rank + 0.40 × tcn_score)? Or was it changed during the alpha model disaster to something else?

---

## PHASE 6: The Alpha Model Disaster — What Happened?

A previous session replaced the working 60/40 blend with a probability-weighted expected return model. v2_selection.py was marked DO NOT TOUCH after rollback. Verify it's actually the correct version.

```bash
echo "=== GIT BLAME on selection file ==="
cd ~/SS/Meridian && git log --oneline -- stages/v2_selection.py | head -10

echo ""
echo "=== Check for any alpha model remnants ==="
grep -n "alpha\|probability.*weight\|expected.*return\|E\[r\]\|weighted.*alpha\|prob.*alpha" ~/SS/Meridian/stages/v2_selection.py

echo ""
echo "=== Reference output to match ==="
echo "AVIG #1 Final=0.79 TCN=0.82 FR=0.99"
echo "CAH  #2 Final=0.77 TCN=0.89 FR=0.89"
echo "BTCZ #3 Final=0.76 TCN=0.71 FR=0.98"
echo "(These were the known-good outputs from the working 60/40 blend)"
```

---

## PHASE 7: TCN v2 Model — Where Is It?

The TCN v2 was trained on Vast.ai A100 with 5 years of data and achieved IC=0.105. It needs to be located and wired in.

```bash
echo "=== All model directories ==="
find ~/SS/Meridian/models/ -type d | sort

echo ""
echo "=== All .pt files (PyTorch models) ==="
find ~/SS/Meridian/ -name "*.pt" | sort

echo ""
echo "=== All model config files ==="
find ~/SS/Meridian/ -name "config.json" -path "*/model*" | sort

echo ""
echo "=== Check if v2 model was downloaded ==="
ls -la ~/SS/Meridian/models/tcn_v2*/ 2>/dev/null
ls -la ~/SS/Meridian/models/tcn_pass_v2*/ 2>/dev/null
ls -la ~/Downloads/*tcn* 2>/dev/null
ls -la ~/Downloads/*model* 2>/dev/null

echo ""
echo "=== Check tcn_scorer for model version handling ==="
grep -n "v1\|v2\|version\|model_dir\|MODEL_DIR" ~/SS/Meridian/stages/tcn_scorer.py | head -15
```

---

## PHASE 8: Factor Engine — Are All 19 Features Being Computed?

```bash
echo "=== Factor registry — active features ==="
python3 -c "
import json
reg = json.load(open('/Users/sjani008/SS/Meridian/config/factor_registry.json'))
for f in reg:
    if f.get('active'):
        print(f'{f[\"name\"]:30s} module={f.get(\"module\",\"?\")}')
" 2>/dev/null || echo "Could not parse factor_registry.json"

echo ""
echo "=== Factor engine — which modules are called? ==="
grep -n "import.*m[1-5]\|from.*m[1-5]\|m1_\|m2_\|m3_\|m4_\|m5_" ~/SS/Meridian/stages/v2_factor_engine.py | head -20

echo ""
echo "=== Factor engine — what columns does it write? ==="
grep -n "factor_matrix_daily\|factor_history\|INSERT\|columns\|df\.columns" ~/SS/Meridian/stages/v2_factor_engine.py | head -20

echo ""
echo "=== Latest factor_matrix_daily — column check ==="
sqlite3 ~/SS/Meridian/data/v2_universe.db "PRAGMA table_info(factor_matrix_daily)" | head -40
sqlite3 ~/SS/Meridian/data/v2_universe.db "PRAGMA table_info(factor_history)" | head -40
```

---

## PHASE 9: Run Evening Pipeline Dry (If Safe)

```bash
echo "=== Test: run orchestrator --dry-run --real-ml ==="
cd ~/SS/Meridian && python3 stages/v2_orchestrator.py --skip-cache --real-ml --dry-run 2>&1 | tail -40
```

If --dry-run doesn't exist, just run:
```bash
echo "=== Test: run tcn_scorer standalone on latest date ==="
cd ~/SS/Meridian && python3 -c "
from stages.tcn_scorer import score_tcn
result = score_tcn()
print(f'Scored: {len(result)} tickers')
print(f'Min: {result[\"tcn_score\"].min():.4f}')
print(f'Max: {result[\"tcn_score\"].max():.4f}')
print(f'Mean: {result[\"tcn_score\"].mean():.4f}')
print(f'Flat 0.5: {(result[\"tcn_score\"] == 0.5).sum()}')
" 2>&1
```

---

## SUMMARY REPORT FORMAT

After running ALL diagnostics above, write a report with these sections:

### 1. Model Inventory
- What model files exist on disk?
- Is TCN v2 (IC=0.105) present? If not, where is it?
- Is TCN v1 (IC=0.031) the one being loaded?

### 2. Stage 4 Flow
- How does the orchestrator call Stage 4?
- Does --real-ml trigger both LGBM and TCN?
- What writes tcn_score to the DB?

### 3. Stage 5 Blend
- Is the 60/40 formula intact?
- Are tcn_scores real or all 0.5?
- Any remnants of the alpha model disaster?

### 4. The Structural NaN Fix
- Is the 0.5 neutral fill masking a deeper problem?
- Which 7 features are missing from factor_history?
- How many dates have full 19-feature coverage?

### 5. Root Cause of 0 Meridian Picks
- What exactly causes the evening report to show 0 picks?
- Is it Stage 4 (scoring), Stage 5 (selection), or the report filter?

### 6. Recommended Fixes (DO NOT IMPLEMENT)
- List each fix needed, in priority order
- For each: what file, what change, estimated risk

**REMEMBER: Report findings only. Do NOT modify any files.**
