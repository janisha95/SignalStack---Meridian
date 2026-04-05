# Known Issues — Mistakes from S1 to NOT Repeat in Meridian

## Critical (caused real problems)

### 1. Feature Train/Inference Mismatch
**What happened:** S2 (training) computed features using different formulas than S1 (inference). 10 of 19 features were wrong. obv_slope was off by 1,000,000x. The RF model learned splits on S2's scale and received S1's scale at inference → constant p_tp output.
**Prevention:** Single `feature_contract.py` imported by BOTH training and inference. Contract hash stamped in model sidecars. Inference rejects models with mismatched hash.

### 2. Raw Non-Stationary Features in Training
**What happened:** The forge schedule trained on 33 features including close, high, low, volume, ma20, ma50, etc. (raw prices). Models memorized price levels → 55% fast-check WR, 22% walk-forward WR (25-30 point gap).
**Prevention:** All 34 Meridian factors are stationary (ratios, z-scores, oscillators, percentiles). No raw prices or volumes.

### 3. RF with max_depth=None
**What happened:** RandomForest trained with unlimited depth + min_samples_leaf=1. Every tree perfectly fit the training data. Amplified the non-stationarity problem.
**Prevention:** LightGBM with max_depth=6, min_child_samples=20, subsample=0.8, colsample_bytree=0.8.

### 4. SPY Data Stale for Days
**What happened:** SPY data was stuck at Mar 19 for 3+ trading days. All relative strength calculations were wrong. Nobody noticed because there was no validation gate.
**Prevention:** Validation gate checks SPY date before pipeline runs. Stale = abort.

### 5. SQLite File Locking on Windows
**What happened:** Multiple processes writing to same SQLite DB without WAL mode → "database is locked" errors. Forward tracker data lost.
**Prevention:** WAL mode + busy_timeout=5000ms on every connection. Single writer process.

## Important (caused confusion or wasted time)

### 6. 36,000 Redundant Data Fetches
**What happened:** 6 strategies × 3,000 tickers = 18,000 fetch_data calls. Each call fetches OHLCV. Same ticker fetched 6 times. SPY fetched 9,000 times.
**Prevention:** Fetch each ticker ONCE. Pre-load into memory dict. Pass to all factor modules as parameter.

### 7. Strategy Files Return None Silently
**What happened:** When a strategy encountered an error, it returned None (counted as FLAT/HOLD). 97% of calls returned FLAT anyway, so errors were invisible in the noise.
**Prevention:** Fail loudly. Raise exceptions. Log errors. Count error rate per run.

### 8. Convergence Formula Not Learned
**What happened:** The convergence ranking used hand-crafted weights (strategy_strength×0.30 + convergence×0.25 + ...). These weights were arbitrary, never validated against outcomes.
**Prevention:** ML model IS the ranking. No hand-crafted composite. Validated via walk-forward IC.

### 9. SRS as a Strategy (60% Fire Rate)
**What happened:** SRS had ±2% RS thresholds that were trivially met. 60.7% of tickers triggered a signal → noise generator flooding the convergence pipeline.
**Prevention:** No strategies in Meridian. RS is a continuous factor computed for every ticker. No fire/no-fire binary gate.

### 10. Universe Name Inconsistency
**What happened:** `alpaca_us_part1/part2` not registered in the server's UNIVERSES dict → HTTP 400 errors from the orchestrator. Multiple naming conventions for the same universe.
**Prevention:** Single universe. No splits. No naming conventions to maintain.

## Low Priority (cosmetic or edge cases)

### 11. Telegram Message Truncation
**What happened:** Reports exceeded Telegram's 4096 char limit. Chunking split mid-sentence. Haiku insights cut off.
**Prevention:** Split at natural boundaries (between picks, not mid-text). Multiple messages.

### 12. Bracket Orders Missing TP Leg on Alpaca
**What happened:** Alpaca paper trading sometimes registers SL but not TP in bracket orders.
**Prevention:** Verify bracket order legs after placement. Alert if TP leg missing.

### 13. Morning Agent Reading Wrong Convergence Format
**What happened:** New convergence pipeline output had flat `shortlist` with `tradeable` flag. Morning agent expected `synthesis.tier1`. Result: 0 picks.
**Prevention:** Define output contracts in STAGE_X_SPEC.md. Consumer code reads from spec, not assumption.
