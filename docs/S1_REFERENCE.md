# S1 Reference — Code to Copy and Code to Avoid

## S1 Architecture (for context, NOT to replicate)

S1 runs 5 strategies across ~3,000 tickers per evening scan. Each strategy produces BUY/SELL/FLAT decisions. An ML gate (RF + NN) filters to ~180 PASS rows. A convergence pipeline ranks the top 25. A scorer (LightGBM) re-ranks by predicted TP probability.

**Problems with S1 that Meridian fixes:**
- 36,000+ fetch_data calls per run (fetches same ticker 6x, once per strategy)
- 9,000+ redundant SPY fetches (should be 1)
- 97% of strategy calls produce HOLD/FLAT with no output value
- ML gate trained on wrong features (10/19 mismatched between S2 training and S1 inference)
- Convergence formula is hand-crafted (not learned from data)
- Strategies make BUY/SELL decisions, throwing away continuous factor values

## Files to Copy (with modifications)

### Stage 1: Cache Pipeline

| S1 File | Location | What to copy | What to change |
|---------|----------|-------------|----------------|
| `fast_universe_cache.py` | ~/SS/Advance/ | Alpaca multi-symbol bars API, 500-batch logic, WAL mode DB setup | Write to Meridian DB. Use ALPACA_KEY env var. |
| `yf_cache_pipeline.py` | ~/SS/Advance/ | `_download_batch()`, `_parse_yf_df()`, `_write_rows()`, diff logic with file fallback | Write to Meridian DB. Source tag: yfinance_v2. |

### Stage 2: Prefilter

| S1 File | Location | What to copy | What to change |
|---------|----------|-------------|----------------|
| `signalstack_prefilter.py` | ~/SS/Advance/ | ADX computation, ATR computation, volume filtering, quality scoring | Add $1 price floor, $500k dollar volume, suffix exclusions. Remove top-N selection (pass all survivors). |
| `signalstack_router.py` | ~/SS/Advance/ | Regime classification (ADX-based) | Tag only, don't route. Every ticker goes to every factor module. |

### Stage 3: Factor Engine

| S1 File | Location | What to copy | What to change |
|---------|----------|-------------|----------------|
| `modules/strategies/rct.py` | ~/SS/Advance/ | FeatureFactory z-score computations: directional_conviction, momentum_acceleration, momentum_impulse, volume_participation, volume_flow_direction, effort_vs_result, volatility_rank, volatility_acceleration, wick_rejection | Extract continuous computation. Remove BUY/SELL decision. Remove ML gate call. Compute for ALL tickers. |
| `modules/strategies/wyckoff.py` | ~/SS/Advance/ | `detect_wyckoff_phase()`: phase detection, confidence, phase_age, vol_bias, structure_quality | Return continuous values. Remove ACCUMULATION/DISTRIBUTION gate. Compute for ALL tickers. |
| `modules/strategies/brf.py` | ~/SS/Advance/ | damage_depth, rollover_strength, ma20_proximity, retracement_quality | Compute partial scores for ALL tickers (not just 5-condition matches). |
| `modules/strategies/mr.py` | ~/SS/Advance/ | leadership_score, pullback_score, shock_magnitude, setup_score | Remove hard gates. Compute continuous scores for ALL tickers. |
| `srs.py` | ~/SS/Advance/ | rs_10d, rs_20d, rs_momentum computation | Keep as enrichment. Add rs_vs_sector using sector_map. |

### Stage 5: Risk / Position Sizing

| S1 File | Location | What to copy | What to change |
|---------|----------|-------------|----------------|
| `s1_paper_executor.py` | ~/SS/Advance/ | `calculate_position()` ATR-based sizing logic, bracket order construction | Adapt for FTMO constraints (0.5-0.8% risk, 8-10 max positions). |

## Files to NOT Copy

| S1 File | Why NOT |
|---------|---------|
| `s1_evening_orchestrator.py` | HTTP-based orchestrator. Meridian is in-process. |
| `s1_convergence_pipeline.py` | Hand-crafted formula. Meridian uses ML ranking. |
| `modules/ml_gate/` | Per-strategy gating. Meridian does batch ML scoring. |
| `modules/ml_gate/feature_extractor.py` | 19-feature contract with known mismatches. Meridian uses expanded 34-feature contract. |
| `signalstack_strategy_registry.py` | Strategy registry pattern. Meridian has no strategies. |
| `agent_server.py` | HTTP server. Meridian has no HTTP layer. |

## S1 Known Issues (don't repeat these)

1. **Feature mismatch:** S2 training computed 10/19 features differently from S1 inference. obv_slope was off by 1,000,000x. Meridian must have a single feature_contract.py used by BOTH training and inference.

2. **RF max_depth=None:** Unlimited depth memorizes training data. Meridian uses max_depth=6, min_child_samples=20.

3. **Raw non-stationary features:** S2's 33-feature set included 14 raw price/volume features (close, high, low, open, volume, ma20, ma50, etc.) that cause fast-to-WF gap. Meridian's 34 factors are ALL stationary/normalized.

4. **Duplicate data fetching:** S1 fetches the same ticker 6x (once per strategy) + SPY 9,000x. Meridian fetches each ticker ONCE and passes the DataFrame to all factor modules.

5. **Silent failures:** S1's strategies return None on error, which gets counted as FLAT. Meridian must fail loudly on errors.

6. **SQLite locking:** S1 had Windows file locking issues. Meridian uses WAL mode + busy_timeout on all DB connections.

7. **Stale SPY data:** S1's SPY was stale at Mar 19 for days. Meridian's validation gate aborts if SPY is stale.

## S1 Model Audit Summary (for reference)

| Model | Features | Issue |
|-------|----------|-------|
| RF (all slots) | 19 CORE_FEATURES | Byte-identical universal model. p_tp compressed 0.38-0.60. Trained on S2's wrong features. |
| NN (Quantile CNN) | 19 CORE_FEATURES | Trained on correct features (shared contract). 69.9% WR on edge. Wider p_tp spread. |
| LightGBM Scorer | 19 CORE_FEATURES | Trained on historical FUC data with correct features. 60.3% top-decile WR. |

Meridian's models will be trained on 34 features using the expanded factor contract, with walk-forward validation and proper regularization.
