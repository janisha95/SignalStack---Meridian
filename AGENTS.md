# Meridian — Quantitative Trading Factor Model

## Project Overview

Meridian is the v2 rebuild of SignalStack — a multi-lane algorithmic trading system. It replaces the strategy-based candidate generation approach (S1) with a pure factor model where every ticker in the universe gets scored on ~34 continuous factors daily. There are no "strategies that generate candidates." The ML model's predicted return IS the ranking signal.

**Owner:** Shan Jani
**Architect:** Claude Opus (Anthropic)
**Stack predecessor:** SignalStack S1 (~/SS/Advance/), S8 (~/SS/SignalStack8/)

## Architecture

```
Cache → Prefilter → Factor Engine → ML Scoring → Selection → Risk Filters → Output
```

7 stages, executed sequentially by a single orchestrator at 5:00pm ET daily.

## Repo Structure

```
~/SS/Meridian/
├── AGENTS.md                   # THIS FILE — read first
├── ROADMAP.md                  # Build plan, timeline, dependencies
├── docs/
│   ├── ARCHITECTURE.md         # Full factor model architecture (from Notion)
│   ├── REQUIREMENTS.md         # Requirements & build plan (from Notion)
│   ├── STAGE_1_CACHE_SPEC.md   # Stage 1 input/output/test/fail contract
│   ├── STAGE_2_PREFILTER_SPEC.md   # (to be written)
│   ├── STAGE_3_FACTORS_SPEC.md     # (to be written)
│   ├── STAGE_4_ML_SPEC.md          # (to be written)
│   ├── STAGE_5_SELECTION_SPEC.md   # (to be written)
│   ├── STAGE_6_RISK_SPEC.md        # (to be written)
│   ├── STAGE_7_ORCHESTRATOR_SPEC.md # (to be written)
│   ├── S1_REFERENCE.md         # S1 code reference — what to copy, what to avoid
│   └── KNOWN_ISSUES.md         # Known issues from S1 to not repeat
├── stages/
│   ├── v2_cache_warm.py        # Stage 1: Cache pipeline
│   ├── v2_prefilter.py         # Stage 2: Universe filter
│   ├── v2_factor_engine.py     # Stage 3: Factor computation (5 modules)
│   ├── v2_ml_scorer.py         # Stage 4: LightGBM + LSTM scoring
│   ├── v2_selection.py         # Stage 5: Residual alpha selection
│   ├── v2_risk_filters.py      # Stage 6: FTMO-constrained risk
│   └── v2_orchestrator.py      # Stage 7: End-to-end pipeline
├── config/
│   ├── ticker_sector_map.json  # GICS sector mapping (621 tickers)
│   └── feature_contract.py     # Shared feature contract (single source of truth)
├── data/
│   ├── v2_universe.db          # Meridian's OWN database (never S1/S8)
│   └── cache_warm_report.json  # Latest cache warm report
├── models/                     # Trained model files (.pkl, .pt, .json sidecars)
├── tests/                      # Unit tests per stage
└── scripts/                    # Utility scripts
```

## Key Principles

1. **Spec before code.** Every stage has a STAGE_X_SPEC.md with Input/Output/Test/Fail contracts. No coding without an approved spec.
2. **Meridian owns its own DB.** Never write to S1 or S8 databases. v2_universe.db is the single source of truth.
3. **No HTTP calls in pipeline.** Everything is in-process. Single Python process with ThreadPoolExecutor for parallelism.
4. **Factor model, not strategy engine.** No BUY/SELL decisions from strategies. Every ticker gets continuous factor scores. ML ranking IS the signal.
5. **Fail-closed.** If the validation gate fails, the pipeline aborts. No silent fallbacks.
6. **Copy utilities, not architecture.** S1's `fast_universe_cache.py` and `yf_cache_pipeline.py` have good data-fetching logic. Copy that. Don't copy the strategy-routing-ML-gate architecture.

## S1 Reference (what to copy, what to avoid)

### COPY from S1:
- `fast_universe_cache.py` — Alpaca multi-symbol bars endpoint, 500-batch logic
- `yf_cache_pipeline.py` — YFinance diff universe, batch download, _parse_yf_df()
- `signalstack_prefilter.py` — ADX/ATR/volume/quality scoring (modify thresholds)
- Strategy factor computations (continuous values only):
  - `rct.py` FeatureFactory z-scores → Technical Core module
  - `wyckoff.py` detect_wyckoff_phase → Structural Phase module
  - `brf.py` damage/rollover factors → Damage/Short-Side module
  - `mr.py` leadership/pullback/shock scores → Mean Reversion module
  - `srs.py` rs_10d/rs_20d computation → Market Context module

### DO NOT COPY from S1:
- Strategy routing (strategies/*.py BUY/SELL decisions)
- ML gate architecture (per-strategy RF/NN gating)
- Convergence pipeline (hand-crafted formula ranking)
- Multiple evening/night/convergence pipeline stages
- HTTP-based orchestrator (S1 runs strategies via HTTP; Meridian is in-process)
- 36,000 fetch_data calls pattern (Meridian fetches once per ticker)

## Environment Variables

```bash
# Required
ALPACA_KEY=pk_...          # Alpaca API key (NOT ALPACA_API_KEY)
ALPACA_SECRET=sk_...       # Alpaca API secret
ANTHROPIC_API_KEY=sk-...   # For Haiku sentiment in reports

# Optional
V2_DB_PATH=~/SS/Meridian/data/v2_universe.db  # Default
TELEGRAM_BOT_TOKEN=...     # For reports
TELEGRAM_CHAT_ID=...       # For reports
S8_URL=http://localhost:8008  # S8 server (bootstrap only)
```

## Build Order

| Stage | Status | Spec | Depends On |
|-------|--------|------|------------|
| 1. Cache Pipeline | 🔨 Building | ✅ APPROVED | Nothing |
| 2. Prefilter | ⬜ Not started | ⬜ Not written | Stage 1 |
| 3. Factor Engine | ⬜ Not started | ⬜ Not written | Stage 2 |
| 4. ML Scoring | ⬜ Not started | ⬜ Not written | Stage 3 |
| 5. Selection | ⬜ Not started | ⬜ Not written | Stage 4 |
| 6. Risk Filters | ⬜ Not started | ⬜ Not written | Stage 5 |
| 7. Orchestrator | ⬜ Not started | ⬜ Not written | Stage 6 |

## For Codex / Claude Code

When starting any task:
1. Read AGENTS.md (this file) first
2. Read ROADMAP.md for context
3. Read the specific STAGE_X_SPEC.md for the stage you're building
4. Read S1_REFERENCE.md for code to copy
5. Build, test, validate against the spec's acceptance criteria
6. Never modify files outside ~/SS/Meridian/
