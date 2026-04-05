# SignalStack Meridian v2 — Architecture & System Document

## 1. System Overview

Meridian is a systematic US equity trading system that uses ML-enhanced factor ranking to identify daily long and short trade candidates. It processes a universe of ~3,000 liquid US stocks through a 7-stage pipeline, scoring each ticker with a blend of cross-sectional factor ranking (60%) and a temporal convolutional network (40%).

### Design Philosophy
- **Factor-first**: 34 technical factors computed daily, rank-normalized cross-sectionally
- **ML-enhanced, not ML-dependent**: System works in fallback mode without ML model (factor_rank only)
- **Walk-forward validated**: All models validated with expanding-window walk-forward, never trained on test data
- **TBM labeling**: Triple Barrier Method style labels (+2% WIN / -1% LOSE / middle excluded) for clean training signal

### Target Performance
- Information Coefficient (IC) > 0.03 across walk-forward windows
- Win rate > 33.3% at 2:1 reward/risk ratio
- Top decile spread > +0.30% per 5-day period

---

## 2. Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    EVENING PIPELINE (4:30pm ET)               │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Stage 1: Cache Warm (v2_cache_warm.py)                      │
│  └─ Download today's bars from Alpaca IEX + yfinance         │
│     └─ 11,000+ tickers, IEX feed, 1Day timeframe             │
│                                                               │
│  Stage 2: Prefilter (v2_prefilter.py)                        │
│  └─ Filter universe to ~2,500 tradeable stocks               │
│     └─ Remove penny stocks, low volume, halted, leveraged     │
│                                                               │
│  Stage 3: Factor Engine (v2_factor_engine.py)                │
│  └─ Compute 34 technical factors for all survivors            │
│     └─ Uses 5 factor modules (m1-m5) + factor_registry.json  │
│     └─ Saves to factor_matrix_daily + factor_history tables   │
│                                                               │
│  Stage 4B: TCN Scorer (tcn_scorer.py)                        │
│  └─ Load 64 days of factor_history per ticker                 │
│  └─ Cross-sectional rank normalize per date                   │
│  └─ Run TCN inference → probability score 0-1                 │
│     └─ 19 features, 64-bar lookback, BCE classifier           │
│                                                               │
│  Stage 5: Selection (v2_selection.py)                        │
│  └─ Blend: 60% factor_rank + 40% tcn_score                  │
│  └─ Select top 20 LONG + top 20 SHORT candidates             │
│     └─ Side-aware factor percentiles                          │
│                                                               │
│  Stage 6: Risk Filters (v2_risk_filters.py)                  │
│  └─ Position sizing (ATR-based)                               │
│  └─ Sector concentration limits                               │
│  └─ Correlation checks                                        │
│  └─ Prop firm compliance (FTMO rules)                         │
│                                                               │
│  Stage 7: API Server (v2_api_server.py)                      │
│  └─ FastAPI on port 8080                                      │
│  └─ Endpoints: /health, /api/candidates, /api/portfolio/state │
│  └─ React dashboard on port 3000 connects here                │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Data Architecture

### Database: v2_universe.db (SQLite, ~2GB)

| Table | Purpose | Rows | Key Columns |
|---|---|---|---|
| daily_bars | OHLCV price data | 11.1M | ticker, date, open, high, low, close, volume |
| prefilter_results | Daily prefilter output | ~2,500/day | ticker, date |
| factor_matrix_daily | Daily factor snapshots (34 cols) | ~3,300/day | ticker, date, 34 factor columns |
| factor_history | TCN scoring history (19 cols) | 1.58M | ticker, date, 19 TCN feature columns |
| training_data | ML training data | varies | ticker, date, factors, forward_return_5d |
| shortlist_daily | Daily picks | 40-60/day | ticker, direction, final_score, tcn_score, factor_rank |

### Data Sources
- **Alpaca**: Primary OHLCV feed (IEX exchange, regular hours only)
- **yfinance**: Gap-fill for tickers missing from Alpaca, fundamental data
- **Options**: PCR and unusual volume for top tickers

### Data Quality Notes
- IEX feed = ~1.4% of total market volume (known/acceptable)
- Close prices are regular-hours 4pm ET (confirmed via NVDA earnings check)
- Stock split adjustment NOT yet applied (raw prices, need adjustment=split)

---

## 4. Factor Engine

### Factor Registry: 50 features across 13 groups

Config: `~/SS/Meridian/config/factor_registry.json`
Helper: `~/SS/Meridian/config/factor_registry.py`

```python
from config.factor_registry import get_active_features
features = get_active_features()  # all active (currently 31)
features = get_active_features(only_groups=['technical_core', 'momentum'])
```

### Factor Modules (stages/factors/)
| Module | Group | Key Factors |
|---|---|---|
| m1_technical_core | Core | adx, bb_position, volatility_rank, momentum_acceleration |
| m2_structure | Structure | wyckoff_phase, damage_depth, ma_alignment, rollover_strength |
| m3_relative_strength | Relative | rs_vs_spy_10d, rs_vs_spy_20d, leadership_score |
| m4_volume | Volume | volume_participation, volume_climax, effort_vs_result |
| m5_composite | Composite | setup_score, pullback_score |

### Top Factors by Individual IC (last 60 dates)
1. leadership_score: +0.064 (77% hit)
2. rs_vs_spy_10d: +0.054 (72%)
3. ma_alignment: +0.053 (67%)
4. setup_score: +0.048 (68%)
5. damage_depth: -0.047 (32%)
6. market_cap_log: +0.041 (78%) — fundamental
7. ma_death_cross_proximity: +0.041 (70%)

---

## 5. ML Model (Stage 4B)

### Production Model: TCN TBM v1

| Parameter | Value |
|---|---|
| Architecture | TCN Classifier (4-layer causal CNN) |
| Channels | 64 → 64 → 64 → 32 |
| Kernel size | 3 with dilations 1, 2, 4, 8 |
| Head | Linear 32→16→1 with sigmoid |
| Dropout | 0.3 |
| Features | 19 (see list below) |
| Lookback | 64 bars |
| Labeling | TBM: +2% = WIN, -1% = LOSE, middle excluded |
| Loss | BCEWithLogitsLoss with pos_weight |
| Optimizer | Adam, lr=1e-3, weight_decay=1e-5 |
| IC | +0.031 (PASS, target >0.03) |
| Hit rate | 68% |
| Spread | +0.56% |

### 19 TCN Features
adx, bb_position, dist_from_ma20_atr, rs_vs_spy_10d, volume_participation, momentum_acceleration, volatility_rank, wyckoff_phase, ma_alignment, leadership_score, setup_score, damage_depth, volume_climax, rs_vs_spy_20d, ma_death_cross_proximity, downside_volume_dominance, phase_confidence, directional_conviction, vix_regime

### Inference Flow
1. Load 64 days of factor_history from DB
2. Cross-sectional rank normalize each feature per date
3. Build (batch, 64, 19) tensor
4. Forward pass through TCN → sigmoid probability
5. Score 0-1 (higher = more likely to outperform)

### Model Files
- `~/SS/Meridian/models/tcn_pass_v1/model.pt` — PyTorch state dict
- `~/SS/Meridian/models/tcn_pass_v1/config.json` — Feature list and params
- State dict uses abbreviated keys: cv, hd, c, b (matched in tcn_scorer.py)

### Key Training Findings
- TBM labeling >> qcut labeling for TCN
- 19 features >> 25 >> 32 >> 34 >> 47 features
- Fundamental features hurt TCN but help tree models
- Classification (BCE) stable; regression (MSE) collapses to constant
- More data is primary lever for IC improvement

---

## 6. Selection & Scoring (Stage 5)

### Blend Formula
```
final_score = 0.60 × factor_rank + 0.40 × tcn_score
```

- factor_rank: cross-sectional percentile of composite factor score (uses all 34 factors)
- tcn_score: TCN probability output (uses 19 features)
- Side-aware: longs and shorts get separate factor percentiles

### Selection
- Top 20 LONG candidates by final_score
- Top 20 SHORT candidates by final_score (inverted)
- Total: 40 candidates per day

### Fallback Mode
When TCN model files are not present:
- tcn_score = 0.5 (neutral) for all tickers
- final_score = factor_rank only
- System still produces valid picks

---

## 7. Risk Management (Stage 6)

### Position Sizing
- ATR-based: risk per trade = portfolio × risk_pct / ATR
- Default risk: 0.5% of portfolio per trade
- Max positions: 10

### Prop Firm Compliance (FTMO)
- Daily loss limit: $5,000 (5% of $100K)
- Max drawdown: 10%
- Min trading days: 10
- Portfolio heat tracking

### Filters
- Sector concentration: max 3 positions in same sector
- Correlation check: avoid highly correlated positions
- Position size cap: max 10% of portfolio per position

---

## 8. Frontend (React Dashboard)

### Stack
- Next.js 16 + React + Tailwind CSS
- Port 3000 (dev), connects to API on port 8080
- Design: "Sovereign Console" — dark navy #0b1326, amber accents

### Pages
| Page | Content |
|---|---|
| Dashboard | Balance, P&L, top candidates, risk oversight, weekly performance |
| Candidates | Full 60-candidate table with sorting, filtering, detail panel |
| Trades | Trade log (live-backed or empty state) |
| Model | Model health, factor importance |
| Settings | Configuration |

### Features
- TradingView embedded chart on ticker click
- Ticker info card (yfinance: price, change%, volume, market cap)
- Quick links: Yahoo Finance, TradingView, Finviz
- Short P&L displayed correctly (inverted for profit)

---

## 9. External Dependencies

| Service | Purpose | Cost |
|---|---|---|
| Alpaca | Brokerage + market data (IEX) | Free (paper) |
| yfinance | Gap-fill data + fundamentals | Free |
| Google Colab Pro | GPU training | CA$13.99/month |
| TradingView | Embedded charts (widget) | Free |

---

## 10. Known Limitations

1. Cache warm Alpaca download intermittently fails (only pulls partial bars)
2. Stock split adjustment not applied to historical data
3. IEX volume is 1.4% of total market (factor calculations based on partial volume)
4. Options data sparse (PCR/unusual vol >50% NaN)
5. Backfill takes ~6 hours per 250 dates on A100 CPU
6. Colab Pro sessions timeout after ~90 minutes of inactivity
7. TCN regression mode collapses to constant predictions (use classification only)
