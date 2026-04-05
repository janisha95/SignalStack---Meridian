# CODEX — Rebuild Meridian Stages 3, 4, 5 — Simple Algo Trader

## IMPORTANT: Read BEFORE changing anything
```bash
# Read the existing code first
cat ~/SS/Meridian/stages/v2_factor_engine.py | head -100
cat ~/SS/Meridian/stages/tcn_scorer.py
cat ~/SS/Meridian/stages/v2_selection.py | head -150
cat ~/SS/Meridian/stages/v2_orchestrator.py | head -100
ls ~/SS/Meridian/stages/factors/
ls ~/SS/Meridian/models/tcn_pass_v1/
ls ~/SS/Meridian/models/tcn_short_v1/
```

## Context

We are simplifying Meridian from a complex factor-rank-blend system to a simple TCN-based algo trader.

**Current architecture (broken):**
- Stage 3: Computes 34 factors via 5 modules (m1-m5)
- Stage 4: LGBM classifier (DEAD — 3 trees, AUC 0.537, zero discrimination)
- Stage 5: Beta stripping → residual_alpha → factor_rank → blend 60% factor_rank + 40% TCN
- Result: Longs 56.7% accuracy, Shorts 6.7% accuracy (catastrophic)

**New architecture (simple):**
- Stage 3: Compute ONLY the 19 TCN features. No m4 (mean_reversion). No LGBM-only features.
- Stage 4: Run Long TCN + Short TCN → scores per ticker
- Stage 5: Rank longs by tcn_long DESC top 5, shorts by tcn_short DESC top 5. Done.
- No LGBM. No beta stripping. No residual_alpha. No factor_rank in ranking.

**Models available:**
- Long TCN: `~/SS/Meridian/models/tcn_pass_v1/model.pt` + `config.json` (IC +0.105)
- Short TCN: `~/SS/Meridian/models/tcn_short_v1/model.pt` + `config.json` (IC +0.392)
- Both use same architecture: 4-layer causal CNN, channels [64,64,64,32], kernel 3, dilations [1,2,4,8]
- Both use same 19 features with 64-day lookback and cross-sectional rank normalization

## Git backup first
```bash
cd ~/SS/Meridian && git add -A && git commit -m "backup: pre-stage-3-4-5-rebuild"
```

---

## CHANGE 1: Stage 3 — Compute only 19 TCN features

### File: `~/SS/Meridian/stages/v2_factor_engine.py`

The current engine loads factor_registry.json and runs all 5 modules (m1-m5) to compute 34 factors.

**Change it to:**
1. Hardcode the 19 TCN features directly (no registry lookup for enabled features)
2. Only call the modules that produce these 19 features
3. Skip m4 (mean_reversion) entirely — it produces: leadership_score, pullback_score, shock_magnitude, setup_score. Wait — leadership_score and setup_score ARE in the 19 TCN features. So m4 CANNOT be fully skipped.

**The 19 TCN features and which module produces each:**
```
FROM m1_technical_core (13 features — keep ALL of m1 except adx):
  directional_conviction, momentum_acceleration, momentum_impulse,
  volume_participation, volume_flow_direction, effort_vs_result,
  volatility_rank, volatility_acceleration, wick_rejection,
  bb_position, ma_alignment, dist_from_ma20_atr
  PLUS: adx (it IS in the 19)

FROM m2_structural_phase (2 features — keep only these 2):
  wyckoff_phase, phase_confidence
  SKIP: phase_age_days, vol_bias, structure_quality

FROM m3_damage_shortside (2 features — keep only these 2):
  damage_depth, rollover_strength  
  SKIP: downside_volume_dominance, ma_death_cross_proximity
  WAIT — downside_volume_dominance IS in the 19. So keep 3:
  damage_depth, rollover_strength, downside_volume_dominance
  SKIP: ma_death_cross_proximity
  WAIT — ma_death_cross_proximity IS also in the 19. Keep ALL 4 of m3.

FROM m4_mean_reversion (2 features — keep only these 2):
  leadership_score, setup_score
  SKIP: pullback_score, shock_magnitude

FROM m5_market_context (3 features — keep only these 3):
  rs_vs_spy_10d, rs_vs_spy_20d, rs_momentum
  SKIP: options_pcr, options_unusual_vol, volume_climax, market_breadth, vix_regime
  WAIT — vix_regime and volume_climax ARE in the 19. Keep 5:
  rs_vs_spy_10d, rs_vs_spy_20d, rs_momentum, volume_climax, vix_regime
  SKIP: options_pcr, options_unusual_vol, market_breadth
```

**ACTUALLY — let me just list all 19 TCN features cleanly:**
```python
TCN_FEATURES = [
    "adx", "bb_position", "dist_from_ma20_atr", "rs_vs_spy_10d",
    "volume_participation", "momentum_acceleration", "volatility_rank",
    "wyckoff_phase", "ma_alignment", "leadership_score", "setup_score",
    "damage_depth", "volume_climax", "rs_vs_spy_20d",
    "ma_death_cross_proximity", "downside_volume_dominance",
    "phase_confidence", "directional_conviction", "vix_regime",
]
```

**Simplest approach:** Keep running all 5 modules as-is (don't modify the modules themselves). After all modules return their factors, FILTER to keep only these 19 features before writing to `factor_matrix_daily` and `factor_history`. This is the safest change — no module code changes, just a filter at the engine level.

```python
# After computing all factors for a ticker
all_factors = {**m1, **m2, **m3, **m4, **m5}
# Filter to TCN features only
tcn_factors = {k: all_factors[k] for k in TCN_FEATURES if k in all_factors}
```

**ALSO:** Extract the full 34-feature computation into a standalone file for future Market Intelligence product:
```bash
cp ~/SS/Meridian/stages/v2_factor_engine.py ~/SS/Meridian/stages/market_intelligence_factors.py
```
This way the full computation is preserved outside the orchestrator pipeline.

### What to write to DB:
- `factor_matrix_daily`: Only 19 columns (was 34)
- `factor_history`: Only 19 columns (this is what TCN reads for scoring)

---

## CHANGE 2: Stage 4 — Dual TCN Scoring (Long + Short)

### File: `~/SS/Meridian/stages/tcn_scorer.py`

Current: Has `TCNScorer` class that loads `tcn_pass_v1` model and scores all tickers.

**Add a `TCNShortScorer` class (or modify existing to support both):**

Simplest approach — add a `model_dir` parameter to `TCNScorer.__init__()`:

```python
class TCNScorer:
    def __init__(self, model_dir=None, db_path=None):
        if model_dir is None:
            model_dir = Path(__file__).parent.parent / "models" / "tcn_pass_v1"
        # ... rest of init
```

Then in the orchestrator, create two instances:
```python
long_scorer = TCNScorer(model_dir="models/tcn_pass_v1")
short_scorer = TCNScorer(model_dir="models/tcn_short_v1")

long_scores = long_scorer.score(run_date)   # Returns DataFrame with ticker, tcn_score
short_scores = short_scorer.score(run_date)  # Returns DataFrame with ticker, tcn_score
```

**CRITICAL:** Both models use the SAME architecture (TCNClassifier with same channels/kernel/dilations). The existing `TCNClassifier` class in `tcn_scorer.py` should work for both. Just point to different model.pt files.

**CRITICAL:** The short TCN was trained on the same 19 features with the same cross-sectional rank normalization. The inference pipeline is IDENTICAL — only the weights differ.

### Write to DB:
Update `predictions_daily` to have:
```sql
CREATE TABLE predictions_daily (
    date TEXT,
    ticker TEXT,
    tcn_long_score REAL,    -- from tcn_pass_v1
    tcn_short_score REAL,   -- from tcn_short_v1
    regime TEXT,
    sector TEXT,
    price REAL,
    PRIMARY KEY (date, ticker)
);
```

Remove `predicted_return`, `lgbm_long_prob`, `lgbm_short_prob`, `top_shap_factors` columns.

### Remove LGBM:
- Do NOT call `lgbm_scorer.py` in the orchestrator
- Do NOT import lgbm_scorer anywhere
- The file can stay on disk, just don't call it

---

## CHANGE 3: Stage 5 — Simple Rank and Pick

### File: `~/SS/Meridian/stages/v2_selection.py`

**THIS FILE IS MARKED "DO NOT TOUCH" from a previous incident. Be extremely careful.**

Current: Loads predictions_daily → computes beta → residual_alpha → calls TCN inline → factor_rank → blend → shortlist

**Replace the ENTIRE selection logic with:**

```python
def run(run_date: str, db_path: str, n_long: int = 5, n_short: int = 5) -> pd.DataFrame:
    """Simple selection: rank by TCN scores, pick top N."""
    
    # Read predictions_daily (now has tcn_long_score and tcn_short_score)
    con = sqlite3.connect(db_path)
    preds = pd.read_sql(f"""
        SELECT ticker, tcn_long_score, tcn_short_score, regime, sector, price
        FROM predictions_daily
        WHERE date = '{run_date}'
    """, con)
    con.close()
    
    if preds.empty:
        print(f"[V5] No predictions for {run_date}")
        return pd.DataFrame()
    
    # LONGS: highest tcn_long_score
    longs = preds.nlargest(n_long, 'tcn_long_score').copy()
    longs['direction'] = 'LONG'
    longs['final_score'] = longs['tcn_long_score']
    longs['rank'] = range(1, len(longs) + 1)
    
    # SHORTS: highest tcn_short_score (high = most likely to drop)
    shorts = preds.nlargest(n_short, 'tcn_short_score').copy()
    shorts['direction'] = 'SHORT'
    shorts['final_score'] = shorts['tcn_short_score']
    shorts['rank'] = range(1, len(shorts) + 1)
    
    shortlist = pd.concat([longs, shorts], ignore_index=True)
    
    # Add legacy columns for API/frontend compatibility (set to 0/neutral)
    shortlist['factor_rank'] = 0.0
    shortlist['residual_alpha'] = 0.0
    shortlist['beta'] = 0.0
    shortlist['market_component'] = 0.0
    shortlist['predicted_return'] = 0.0
    shortlist['tcn_score'] = shortlist.apply(
        lambda r: r['tcn_long_score'] if r['direction'] == 'LONG' else r['tcn_short_score'], axis=1
    )
    
    # Write to shortlist_daily
    shortlist['date'] = run_date
    
    con = sqlite3.connect(db_path)
    con.execute(f"DELETE FROM shortlist_daily WHERE date = '{run_date}'")
    shortlist.to_sql('shortlist_daily', con, if_exists='append', index=False)
    con.commit()
    con.close()
    
    print(f"[V5] Selection complete: {len(longs)} LONG + {len(shorts)} SHORT")
    for _, r in longs.iterrows():
        print(f"  ↑ {r['ticker']:8s} tcn_long={r['tcn_long_score']:.3f}")
    for _, r in shorts.iterrows():
        print(f"  ↓ {r['ticker']:8s} tcn_short={r['tcn_short_score']:.3f}")
    
    return shortlist
```

**This replaces ALL the beta stripping, residual_alpha, factor_rank, blend logic.**

---

## CHANGE 4: Orchestrator — Wire the new stages

### File: `~/SS/Meridian/stages/v2_orchestrator.py`

Find the function that runs Stage 4 (probably `_run_stage4_real()` or similar).

**Change it to:**
1. Create two TCNScorer instances (long + short)
2. Score all tickers with both
3. Merge scores into one DataFrame
4. Write to `predictions_daily` with new schema

Find the function that runs Stage 5 (probably `_run_stage5()` or similar).

**Change it to:**
1. Call the new simple `v2_selection.run()` 
2. Remove any inline TCN calls (TCN is now in Stage 4)

```bash
# Read the orchestrator to find exact function names
grep -n "def.*stage.*4\|def.*stage.*5\|def.*real\|def.*selection\|def.*predict\|def.*score\|def.*tcn" ~/SS/Meridian/stages/v2_orchestrator.py | head -20
```

---

## CHANGE 5: Extract 34-feature computation for Market Intelligence

```bash
# Copy the current factor engine as the MI standalone script
cp ~/SS/Meridian/stages/v2_factor_engine.py ~/SS/Meridian/stages/market_intelligence_factors.py

# Add a comment at the top
sed -i '' '1s/^/# STANDALONE: Full 34-feature computation for Market Intelligence product\n# NOT part of the orchestrator pipeline — run separately\n/' ~/SS/Meridian/stages/market_intelligence_factors.py
```

This file stays unchanged and can be called independently for the MI product.

---

## Verification

```bash
# 1. Compile check
python3 -m py_compile ~/SS/Meridian/stages/v2_factor_engine.py
python3 -m py_compile ~/SS/Meridian/stages/tcn_scorer.py
python3 -m py_compile ~/SS/Meridian/stages/v2_selection.py
python3 -m py_compile ~/SS/Meridian/stages/v2_orchestrator.py

# 2. Check models exist
ls -la ~/SS/Meridian/models/tcn_pass_v1/model.pt
ls -la ~/SS/Meridian/models/tcn_short_v1/model.pt

# 3. Dry run the orchestrator
cd ~/SS/Meridian && python3 stages/v2_orchestrator.py --real-ml --dry-run 2>&1 | tail -30

# 4. Real run
cd ~/SS/Meridian && python3 stages/v2_orchestrator.py --real-ml 2>&1 | tail -50

# 5. Verify shortlist output
sqlite3 ~/SS/Meridian/data/v2_universe.db "
SELECT ticker, direction, tcn_long_score, tcn_short_score, final_score, rank
FROM shortlist_daily
WHERE date = (SELECT MAX(date) FROM shortlist_daily)
ORDER BY direction, rank
"

# Expected: 5 LONG + 5 SHORT ranked by TCN scores
```

## Commit
```bash
cd ~/SS/Meridian && git add -A && git commit -m "rebuild: Stage 3/4/5 — simple algo trader, dual TCN, no LGBM/factor_rank"
```
