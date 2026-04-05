# SignalStack Meridian v2 — Current State & System Document
# Last Updated: Mar 28, 2026

## 1. What Meridian Does

Meridian scans ~3,000 US equities daily, scores and ranks candidates using a TCN classifier + factor rankings, and produces 30 LONG + 30 SHORT candidates for a 5-day hold strategy. The ML layer uses Triple Barrier Method (TBM) meta-labeling to filter rule-based signals.

Target: win rate >33.3% at 2:1 R/R. Validated: 52.4% WR on 5-day holds.

## 2. Pipeline Architecture

```
5:00 PM ET Daily (automated via launchd):

Stage 1: Cache Warm (v2_cache_warm.py)
  └─ Downloads today's bars from Alpaca IEX + yfinance
  └─ 11,000+ tickers, IEX feed, 1Day timeframe
  └─ Writes to: daily_bars table in v2_universe.db

Stage 2: Prefilter (v2_prefilter.py)
  └─ Filters universe to ~2,500-4,000 tradeable stocks
  └─ Removes: penny stocks (<$1), low volume (<200K shares),
     halted, leveraged/inverse ETFs, earnings-day stocks
  └─ Takes 10-15 minutes on 2.9GB DB — this is normal

Stage 3: Factor Engine (v2_factor_engine.py)
  └─ Computes 34 technical factors for all survivors
  └─ Uses 5 factor modules (m1-m5) + factor_registry.json
  └─ Writes to: factor_matrix_daily + factor_history tables
  └─ Takes ~18 minutes for 4,000 tickers

Stage 4B: TCN Scorer (tcn_scorer.py)
  └─ Loads 64 days of factor_history per ticker
  └─ Cross-sectional rank normalizes per date
  └─ Runs TCN inference → probability score 0-1
  └─ 19 features, 64-bar lookback, BCE classifier
  └─ Model: ~/SS/Meridian/models/tcn_pass_v1/

Stage 5: Selection (v2_selection.py) *** DO NOT TOUCH ***
  └─ Blend: final_score = 0.60 × factor_rank + 0.40 × tcn_score
  └─ LONG: factor_rank = percentile(residual_alpha) within LONG pool
  └─ SHORT: final_score = 0.60 × factor_rank + 0.40 × (1 - tcn_score)
  └─ Selects top 30 LONG + top 30 SHORT
  └─ Writes to: shortlist_daily table

Stage 6: Risk Filters (v2_risk_filters.py)
  └─ ATR-based position sizing
  └─ Sector concentration limits (max 2 per sector)
  └─ Correlation checks (>0.85 = skip)
  └─ Prop firm compliance rules
  └─ CONFIRMED: risk_config.json has TTP Day Trade $50K rules:
     - account_balance: 50000
     - max_daily_loss_pct: 0.02 (2% = $1,000)
     - max_total_drawdown_pct: 0.04 (4% = $2,000)
     - profit_target_pct: 0.06 (6% = $3,000)
     - must_close_eod: true
     - no_new_trades_after: 15:00
     - eod_close_time: 15:30
     - block_earnings_same_day: true
     - block_leveraged_inverse: true
     - block_low_volume: 200000
     - max_positions: 5
     - risk_per_trade_pct: 0.004 (0.4%)
  └─ Also has presets: trade_the_pool_day_100k, trade_the_pool_swing_10k, ftmo
  └─ NOTE: Orchestrator CLI may default to --prop-firm ftmo label
     but actual defaults in config ARE TTP. Explicitly pass 
     --prop-firm trade_the_pool_day_50k to be safe.
  └─ Writes to: tradeable_portfolio table

Stage 7: Orchestrator + API (v2_orchestrator.py + v2_api_server.py)
  └─ FastAPI on port 8080
  └─ Endpoints: /health, /api/candidates, /api/portfolio/state
  └─ React dashboard on port 3000 (Vercel deployed)
  └─ Cloudflare tunnel exposes local API

Forward Tracker (v2_forward_tracker.py)
  └─ Snapshots daily picks into pick_tracking table
  └─ Evaluates after 5 days: WIN (+2%), LOSE (-1%), TIMEOUT
  └─ 120 picks pending (first batch resolves Apr 2)
```

## 3. Database

**File:** `~/SS/Meridian/data/v2_universe.db` (~2.9 GB)

**Key tables:**
- `daily_bars` — OHLCV for 11,000+ tickers (years of history)
- `factor_matrix_daily` — 34 factors per ticker per date
- `factor_history` — rolling factor values (for TCN lookback)
- `shortlist_daily` — 30L + 30S candidates per date
- `pick_tracking` — forward tracking picks (snapshot + evaluation)
- `tradeable_portfolio` — risk-filtered positions with sizing
- `portfolio_state` — daily account state (P&L, drawdown, heat)
- `training_data` — backfill data for ML training (83.3% complete)
- `predictions_daily` — TCN scores per ticker per date

## 4. TCN Model

**Architecture:** 4-layer causal CNN (Temporal Convolutional Network)
- Channels: 64 → 64 → 64 → 32
- Kernel size 3, dilations 1, 2, 4, 8
- Head: Linear 32→16→1 with sigmoid
- Loss: BCEWithLogitsLoss with pos_weight

**Training:** TBM labels (+2% WIN, -1% LOSE, middle excluded)
- IC: +0.031 (PASS, target >0.03)
- Hit rate: 68%
- Spread: +0.56%

**19 Features:**
adx, bb_position, dist_from_ma20_atr, rs_vs_spy_10d, volume_participation,
momentum_acceleration, volatility_rank, wyckoff_phase, ma_alignment,
leadership_score, setup_score, damage_depth, volume_climax, rs_vs_spy_20d,
ma_death_cross_proximity, downside_volume_dominance, phase_confidence,
directional_conviction, vix_regime

**Critical limitation:** ONE-SIDED classifier. It asks "will this stock hit +2%
before -1%?" — fundamentally a bullish question. Low scores ≠ "will go down",
could mean sideways. Meridian SHORT picks are weak signal (use S1 LightGBM
Scorer for shorts instead).

**Model files:**
- `~/SS/Meridian/models/tcn_pass_v1/model.pt`
- `~/SS/Meridian/models/tcn_pass_v1/config.json`

## 5. 34 Factor Modules

**m1_technical_core.py** (bottleneck: 27.8s/250 tickers in backfill)
- adx, directional_conviction, momentum_acceleration, momentum_impulse
- volume_participation, volume_flow_direction, effort_vs_result
- volatility_rank, volatility_acceleration, wick_rejection
- bb_position, ma_alignment, dist_from_ma20_atr

**m2_structural_phase.py** (fast: 0.93s/250 tickers)
- wyckoff_phase, phase_confidence, phase_age_days, vol_bias, structure_quality

**m3_damage_shortside.py** (4.45s/250 tickers)
- damage_depth, rollover_strength, downside_volume_dominance
- ma_death_cross_proximity

**m4_mean_reversion.py** (10.2s/250 tickers)
- leadership_score, pullback_score, shock_magnitude, setup_score

**m5_market_context.py** (fast: 0.29s/250 tickers)
- rs_vs_spy_10d, rs_vs_spy_20d, rs_momentum
- options_pcr, options_unusual_vol (>50% NaN — excluded from TCN)
- volume_climax, market_breadth, vix_regime

## 6. Selection Logic (Stage 5) — DO NOT MODIFY

```python
# LONG candidates:
factor_rank = percentile(residual_alpha) within LONG pool
final_score = 0.60 × factor_rank + 0.40 × tcn_score

# SHORT candidates:
factor_rank = percentile(residual_alpha) within SHORT pool
final_score = 0.60 × factor_rank + 0.40 × (1 - tcn_score)
```

This is Option D from the original spec. It was rebuilt from scratch after a
production crisis where another chat rewrote it with probability-weighted E[r]
and beta stripping, causing inverse/leveraged ETFs to dominate rankings.

**NEVER MODIFY v2_selection.py without git backup first.**

## 7. Automation (OPERATIONAL)

**Files:**
- `~/SS/boot_signalstack.sh` — starts Meridian API (8080), S1 API (8000), Cloudflare tunnel
- `~/SS/run_evening.sh` — full evening: FUC cache → boot → Meridian → S1
- `~/SS/health_check.sh` — status check all services

**Schedule (launchd):**
- `com.signalstack.evening` — 5:00 PM ET Mon-Fri (both pipelines)
- `com.signalstack.morning` — 6:30 AM ET Mon-Fri (morning report)

**Mac wake/sleep (needs sudo activation):**
```bash
sudo pmset repeat wakeorpoweron MTWRF 16:55:00
sudo pmset repeat sleep MTWRF 23:00:00
```

## 8. Frontend

- Next.js 16 + React + Tailwind CSS
- Deployed on Vercel (signalstack-app.vercel.app)
- Design: "Sovereign Console" — dark navy #0b1326, amber accents
- Pages: Dashboard, Candidates, Trades, Model, Settings
- TradingView embedded charts, ticker info cards
- Connects to local API via Cloudflare tunnel

## 9. Backfill Status

- 83.3% complete (1199/1440 dates, 241 remaining)
- Bottleneck: m1_technical_core (27.8s/250 tickers), m4_mean_reversion (10.2s)
- ETA: should complete Saturday evening
- When done → retrain TCN on full 5-year data

## 10. Forward Tracking

- 120 picks snapshotted (Mar 26 + 27)
- PENDING evaluation — first batch resolves Apr 2
- TBM thresholds: WIN = +2%, LOSE = -1%, TIMEOUT = actual return
- CLI: `--snapshot`, `--evaluate`, `--backfill --start-date`, `--summary`
- API: `GET /api/tracking/summary`

## 11. Validated Signal Quality (from S1 sister system)

### LONG signals (use for morning report):
| Signal | WR | Picks | Source |
|---|---|---|---|
| NN (nn_p_tp 0.90-0.95) | 73% | 15 | S1 |
| Dual RF≥0.50 + NN≥0.50 | 65% | 46 | S1 |
| RF (p_tp 0.60+) | 60% | 10 | S1 |
| Convergence LONG ≥0.80 | TBD | TBD | S1 (JSON) |
| Meridian TCN≥0.70, FR≥0.80 | TBD | 11 | Meridian |

### SHORT signals:
| Signal | WR | Source | Use? |
|---|---|---|---|
| LightGBM Scorer ≥0.55 | 71% dir | S1 | ✅ BEST |
| Convergence SHORT ≥0.60 | 67% | S1 | ✅ |
| Meridian shorts (inverted TCN) | ~40% dir | Meridian | ⚠️ TOP 3 ONLY |
| rct_short gate | 6% | S1 | ❌ AVOID |
| srs SHORT | 21% | S1 | ❌ AVOID |

### Critical data points:
- 5-day swing WR: 52.4% (ABOVE 33.3% breakeven) ✅
- Intraday WR: 32.1% (BELOW breakeven) ❌
- 82% of TP/SL hits happen on first 5-min bar (overnight gap)
- System edge lives in multi-day timeframe

## 12. Known Issues

1. Stage 6 label says "FTMO" — verify risk_config.json has TTP rules
2. IEX volume is 1.4% of total market (factor calculations on partial volume)
3. Options data sparse (PCR/unusual vol >50% NaN — excluded from TCN)
4. TCN is one-sided classifier — no dedicated short model
5. Backfill Stage 3 prefilter reruns inside factor_engine.py (double compute)
6. Cache warm Alpaca download intermittently fails (partial bars)
7. Stock splits not adjusted in historical data

## 13. DO NOT TOUCH

- `v2_selection.py` — rebuilt from scratch, git committed, working
- `tcn_scorer.py` — Stage 4B, working
- `v2_forward_tracker.py` — just built, working
- Any ML model files in `models/`
- S1 strategy files in `~/SS/Advance/modules/`

## 14. File Structure

```
~/SS/Meridian/
├── stages/
│   ├── v2_cache_warm.py        # Stage 1
│   ├── v2_prefilter.py         # Stage 2
│   ├── v2_factor_engine.py     # Stage 3
│   ├── factors/
│   │   ├── m1_technical_core.py
│   │   ├── m2_structural_phase.py
│   │   ├── m3_damage_shortside.py
│   │   ├── m4_mean_reversion.py
│   │   └── m5_market_context.py
│   ├── tcn_scorer.py           # Stage 4B
│   ├── v2_selection.py         # Stage 5 *** DO NOT TOUCH ***
│   ├── v2_risk_filters.py      # Stage 6
│   ├── v2_orchestrator.py      # Stage 7
│   ├── v2_api_server.py        # API
│   ├── v2_forward_tracker.py   # Forward tracking
│   └── v2_training_backfill.py # Backfill for ML training
├── models/
│   └── tcn_pass_v1/
│       ├── model.pt
│       └── config.json
├── config/
│   ├── factor_registry.json
│   ├── risk_config.json
│   └── ticker_sector_map.json
├── data/
│   └── v2_universe.db          # 2.9 GB SQLite
├── docs/
│   ├── meridian_architecture_system_doc.md
│   ├── REBUILD_STAGE5_FROM_SCRATCH.md
│   ├── STAGE6_TTP_DAY_TRADE_50K.md
│   └── MERIDIAN_ALPHA_MODEL_AND_FORWARD_TRACKING_SPEC.md
├── ui/
│   └── signalstack-app/        # Next.js React dashboard
└── logs/

~/SS/Advance/                    # S1 (sister system)
├── agent_server.py              # FastAPI backend (~7,100 lines)
├── s1_orchestrator_v2.py        # S1 orchestrator
├── s1_morning_agent.py          # Old morning report (v1)
├── signalstack_metrics.db       # S1 database
└── modules/                     # S1 strategy modules

~/SS/
├── boot_signalstack.sh          # Starts all services
├── run_evening.sh               # Runs both pipelines
├── health_check.sh              # Status check
└── logs/
```

## 15. External Dependencies

| Service | Purpose | Cost |
|---|---|---|
| Alpaca | Market data (IEX feed) + paper/live trading | Free |
| yfinance | Gap-fill data + fundamentals | Free |
| Cloudflare | Tunnel to expose local API | Free |
| Vercel | React dashboard hosting | Free |
| Google Colab Pro | GPU training (when needed) | CA$13.99/mo |
| Anthropic API | Haiku for morning report sentiment | Pay per use |
| Telegram Bot | Morning/evening report delivery | Free |

## 16. Prop Firm Target

**Trade The Pool (TTP)** — only viable option for full US equity coverage.
- Day Trade $50K-$100K: 6% target, 4% DD, 2% daily loss, close by EOD
- Swing $20K-$40K: 15% target, 7% DD, 3% daily loss, overnight OK
- 12,000+ real US stocks and ETFs (not CFDs)
- Decision pending based on system readiness

## 17. Next Steps

1. ✅ Automation: Both pipelines scheduled at 5 PM, morning report at 6:30 AM
2. 🔲 Morning report v2: Consolidated S1 + Meridian with corrected thresholds
3. 🔲 Stage 6: Verify TTP rules in risk_config.json (may still show FTMO)
4. 🔲 Backfill completion → retrain TCN on full 5-year data
5. 🔲 Short-side TCN: Test inverted TBM labels after backfill
6. 🔲 Forward tracking: First batch resolves Apr 2
7. 🔲 TTP demo: Register for 14-day free trial this week
8. 🔲 Intraday system: 13 specs ready, build starts Sunday
9. 🔲 F&O expansion: Add indices/forex/commodities to universe
