# Meridian Repo Audit

## 1. Files / docs reviewed

Repo structure and key files reviewed:
- [/Users/sjani008/SS/Meridian/AGENTS.md](/Users/sjani008/SS/Meridian/AGENTS.md)
- [/Users/sjani008/SS/Meridian/README.md](/Users/sjani008/SS/Meridian/README.md)
- [/Users/sjani008/SS/Meridian/MERIDIAN_CURRENT_STATE.md](/Users/sjani008/SS/Meridian/MERIDIAN_CURRENT_STATE.md)
- [/Users/sjani008/SS/Meridian/ROADMAP.md](/Users/sjani008/SS/Meridian/ROADMAP.md)
- [/Users/sjani008/SS/Meridian/AUTOMATION_AND_SCHEDULING_SPEC.md](/Users/sjani008/SS/Meridian/AUTOMATION_AND_SCHEDULING_SPEC.md)
- [/Users/sjani008/SS/Meridian/docs/meridian_architecture_system_doc.md](/Users/sjani008/SS/Meridian/docs/meridian_architecture_system_doc.md)
- [/Users/sjani008/SS/Meridian/docs/OPERATIONAL_STANDARDS.md](/Users/sjani008/SS/Meridian/docs/OPERATIONAL_STANDARDS.md)
- [/Users/sjani008/SS/Meridian/docs/KNOWN_ISSUES.md](/Users/sjani008/SS/Meridian/docs/KNOWN_ISSUES.md)
- [/Users/sjani008/SS/Meridian/docs/S1_REFERENCE.md](/Users/sjani008/SS/Meridian/docs/S1_REFERENCE.md)
- [/Users/sjani008/SS/Meridian/docs/STAGE_4B_MODEL_TRAINER_SPEC.md](/Users/sjani008/SS/Meridian/docs/STAGE_4B_MODEL_TRAINER_SPEC.md)
- [/Users/sjani008/SS/Meridian/docs/STAGE_5_SELECTION_SPEC.md](/Users/sjani008/SS/Meridian/docs/STAGE_5_SELECTION_SPEC.md)
- [/Users/sjani008/SS/Meridian/docs/STAGE_7_ORCHESTRATOR_SPEC.md](/Users/sjani008/SS/Meridian/docs/STAGE_7_ORCHESTRATOR_SPEC.md)
- [/Users/sjani008/SS/Meridian/docs/deployment_maintenance_guide.md](/Users/sjani008/SS/Meridian/docs/deployment_maintenance_guide.md)

Runtime/backend files reviewed:
- [/Users/sjani008/SS/Meridian/stages/v2_cache_warm.py](/Users/sjani008/SS/Meridian/stages/v2_cache_warm.py)
- [/Users/sjani008/SS/Meridian/stages/v2_prefilter.py](/Users/sjani008/SS/Meridian/stages/v2_prefilter.py)
- [/Users/sjani008/SS/Meridian/stages/v2_factor_engine.py](/Users/sjani008/SS/Meridian/stages/v2_factor_engine.py)
- [/Users/sjani008/SS/Meridian/stages/v2_training_backfill.py](/Users/sjani008/SS/Meridian/stages/v2_training_backfill.py)
- [/Users/sjani008/SS/Meridian/stages/v2_fundamental_enrichment.py](/Users/sjani008/SS/Meridian/stages/v2_fundamental_enrichment.py)
- [/Users/sjani008/SS/Meridian/stages/tcn_scorer.py](/Users/sjani008/SS/Meridian/stages/tcn_scorer.py)
- [/Users/sjani008/SS/Meridian/stages/lgbm_scorer.py](/Users/sjani008/SS/Meridian/stages/lgbm_scorer.py)
- [/Users/sjani008/SS/Meridian/stages/v2_selection.py](/Users/sjani008/SS/Meridian/stages/v2_selection.py)
- [/Users/sjani008/SS/Meridian/stages/v2_risk_filters.py](/Users/sjani008/SS/Meridian/stages/v2_risk_filters.py)
- [/Users/sjani008/SS/Meridian/stages/v2_orchestrator.py](/Users/sjani008/SS/Meridian/stages/v2_orchestrator.py)
- [/Users/sjani008/SS/Meridian/stages/v2_api_server.py](/Users/sjani008/SS/Meridian/stages/v2_api_server.py)
- [/Users/sjani008/SS/Meridian/stages/v2_forward_tracker.py](/Users/sjani008/SS/Meridian/stages/v2_forward_tracker.py)
- [/Users/sjani008/SS/Meridian/scripts/train_lgbm.py](/Users/sjani008/SS/Meridian/scripts/train_lgbm.py)
- [/Users/sjani008/SS/Meridian/config/factor_registry.json](/Users/sjani008/SS/Meridian/config/factor_registry.json)
- [/Users/sjani008/SS/Meridian/config/factor_registry.py](/Users/sjani008/SS/Meridian/config/factor_registry.py)
- [/Users/sjani008/SS/Meridian/config/risk_config.json](/Users/sjani008/SS/Meridian/config/risk_config.json)

React app files reviewed:
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/AGENTS.md](/Users/sjani008/SS/Meridian/ui/signalstack-app/AGENTS.md)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/README.md](/Users/sjani008/SS/Meridian/ui/signalstack-app/README.md)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/package.json](/Users/sjani008/SS/Meridian/ui/signalstack-app/package.json)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/next.config.ts](/Users/sjani008/SS/Meridian/ui/signalstack-app/next.config.ts)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/layout.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/layout.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/page.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/page.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/candidates/page.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/candidates/page.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/model/page.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/model/page.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/settings/page.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/settings/page.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/app/trades/page.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/app/trades/page.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/dashboard-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/dashboard-client.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidates-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/candidates-client.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/model-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/model-client.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/settings-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/settings-client.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/trades-client.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/trades-client.tsx)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts](/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts)
- [/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/mock-data.ts](/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/mock-data.ts)

Live state / validation checked:
- SQLite live DB: [/Users/sjani008/SS/Meridian/data/v2_universe.db](/Users/sjani008/SS/Meridian/data/v2_universe.db)
- Test suite: `python3 -m pytest -q` in repo root

## 2. Intended architecture from docs

The intended Meridian architecture is consistent in its higher-level shape but inconsistent in detail across docs.

Stable intent across docs:
- Meridian is a 7-stage, factor-first US equities system.
- Stage 1 caches daily OHLCV and options data into one SQLite DB.
- Stage 2 prefilters to a liquid tradeable universe.
- Stage 3 computes a shared factor matrix instead of S1-style per-strategy decisions.
- Stage 4 produces ML scores from backfilled training data.
- Stage 5 selects top long/short candidates.
- Stage 6 risk-filters and sizes positions.
- Stage 7 orchestrates the evening pipeline and exposes an API for the UI.

Where the docs diverge:
- [/Users/sjani008/SS/Meridian/AGENTS.md](/Users/sjani008/SS/Meridian/AGENTS.md) and [/Users/sjani008/SS/Meridian/ROADMAP.md](/Users/sjani008/SS/Meridian/ROADMAP.md) still read like a pre-build plan and are materially stale.
- [/Users/sjani008/SS/Meridian/MERIDIAN_CURRENT_STATE.md](/Users/sjani008/SS/Meridian/MERIDIAN_CURRENT_STATE.md) is the closest doc to the live implementation.
- [/Users/sjani008/SS/Meridian/docs/meridian_architecture_system_doc.md](/Users/sjani008/SS/Meridian/docs/meridian_architecture_system_doc.md) is polished but partially stale:
  - says top 20 long + 20 short, while live code does 30 + 30
  - says FTMO risk, while config/code have TTP presets and Stage 6 code defaults to TTP
  - presents Stage 4B as production scoring, but the live orchestrator still writes mock predictions
- Stage 4 specs describe a proper model-trainer stage, but there is no formal `v2_model_trainer.py` implementation in the repo.

Net: the intended architecture is a daily factor/ML pipeline with API/UI, but the implementation currently mixes:
- a mostly real Stage 1/2/3/5/6/7 runtime
- offline research/training scripts for 4A/4B
- docs from at least three different eras of the build

## 3. Actual implementation state

### Built

These parts are clearly real, non-trivial, and exercised:

- Stage 1 cache pipeline:
  - downloads Alpaca bars, yfinance diff fill, and options data
  - writes `daily_bars`, `options_daily`, `cache_meta`
  - has validation gate logic and recent bug-fix history
- Stage 2 prefilter:
  - reads Stage 1 DB
  - writes `prefilter_results`
  - computes ADX / ATR / regime
- Stage 3 factor engine:
  - computes factors using five modules under [/Users/sjani008/SS/Meridian/stages/factors](/Users/sjani008/SS/Meridian/stages/factors)
  - writes `factor_matrix_daily`
  - writes TCN feature subset to `factor_history` through the orchestrator
- Stage 4A backfill:
  - historical factor/training-data backfill exists and writes `training_data`
- Stage 4B inference:
  - TCN inference loader is real
  - LGBM inference loader is real
  - model artifacts exist on disk
- Stage 5 selection:
  - selection code is real and writes `shortlist_daily`
  - uses residual alpha + TCN blend
- Stage 6 risk:
  - position sizing and filtering code is real
  - writes `tradeable_portfolio` and `portfolio_state`
- Stage 7 orchestrator and API:
  - orchestrator is real and logs stage outcomes
  - FastAPI server is real and exposes candidates, portfolio, model health, tracking, risk sizing, and broker-facing trade endpoints
- Forward tracker:
  - snapshots picks and evaluates TBM outcomes into `pick_tracking`
- React app:
  - real multi-page Next.js app
  - wired to the live API, not a pure mock shell

Evidence of live operation:
- `v2_universe.db` is populated with current 2026-03-29 rows in `factor_matrix_daily`, `shortlist_daily`, `predictions_daily`, `tradeable_portfolio`, and `pick_tracking`
- `orchestrator_log` has recent Stage 1-6 outcomes
- `shortlist_daily` has 240 rows total and recent dates
- `tradeable_portfolio` has recent approved/rejected rows

### Partial / stubbed

- Stage 4 in the nightly runtime is still partial:
  - the live orchestrator’s Stage 4 path is `_run_stage4_mock()`
  - `orchestrator_log` shows stage `4` status `MOCK`
  - `predictions_daily` stores `predicted_return` from mock generation, not true model inference
- LGBM is present but not wired into the canonical nightly selection flow:
  - [/Users/sjani008/SS/Meridian/stages/lgbm_scorer.py](/Users/sjani008/SS/Meridian/stages/lgbm_scorer.py) exists
  - `scripts/train_lgbm.py` exists
  - but Stage 5 does not use `lgbm_score`, and the orchestrator does not score through LGBM
- Formal Stage 4B trainer is partial as a repo feature:
  - no `v2_model_trainer.py`
  - training is split between backfill, fundamental enrichment, external CSV export, and a standalone LGBM script
- React app is production-ish but not fully canonical:
  - it is live-data capable
  - but still carries demo-mode and mock-data assumptions
  - several adapters are FTMO-biased and not aligned with live Stage 6 settings

### Missing

- No formal, self-contained model training pipeline matching the Stage 4B specs:
  - no canonical trainer entrypoint
  - no canonical walk-forward report generator in repo runtime
- No dedicated short model in Meridian:
  - TCN is long/bullish-oriented
  - current shorts are generated by inverting TCN contribution in Stage 5
- No clean, unified execution subsystem:
  - API exposes trade endpoints to Alpaca paper
  - `trade_log` is still empty in the live DB
  - there is no validated execution reconciliation layer inside Meridian
- No repo-internal automation scripts for the full system described in current-state doc:
  - `~/SS/run_evening.sh` and `~/SS/boot_signalstack.sh` are referenced externally, not kept inside this repo

### Legacy / superseded

- [/Users/sjani008/SS/Meridian/AGENTS.md](/Users/sjani008/SS/Meridian/AGENTS.md) and [/Users/sjani008/SS/Meridian/ROADMAP.md](/Users/sjani008/SS/Meridian/ROADMAP.md) are stale relative to the codebase
- [/Users/sjani008/SS/Meridian/stages/v2_selection.py.broken_backup](/Users/sjani008/SS/Meridian/stages/v2_selection.py.broken_backup) is explicit legacy debris
- [/Users/sjani008/SS/Meridian/data/meridian.db](/Users/sjani008/SS/Meridian/data/meridian.db) is zero-byte and not the live DB
- Root model artifacts such as [/Users/sjani008/SS/Meridian/models/meridian_tcn_pass_model.pt](/Users/sjani008/SS/Meridian/models/meridian_tcn_pass_model.pt) appear superseded by `models/tcn_pass_v1/`
- The UI repo includes checked-in build/runtime artifacts:
  - `node_modules/`
  - `.next/`
  - `output/`
  These are deployment noise, not source-of-truth app code.

## 4. Stage-by-stage audit

### Stage 1

Implementation truth:
- Implemented in [/Users/sjani008/SS/Meridian/stages/v2_cache_warm.py](/Users/sjani008/SS/Meridian/stages/v2_cache_warm.py)
- Creates/uses:
  - `daily_bars`
  - `options_daily`
  - `cache_meta`
- Runs Alpaca batch download, yfinance diff fill, top-N options pull, then validation gate

Dependencies:
- Alpaca env vars
- yfinance
- optional `exchange_calendars` for trading-day resolution
- sector map JSON

DB/table contracts:
- `daily_bars(ticker,date,open,high,low,close,volume,source)`
- `options_daily(ticker,date,pcr,unusual_vol_ratio,net_delta,source)`
- `cache_meta(key,value,updated_at)`

Current health / blockers:
- Built and active
- Fail-closed validation is real
- Supports last-trading-day logic for SPY staleness
- Still noisy on yfinance delisted/missing tickers, but that is data hygiene noise, not a structural blocker
- One test currently fails because validation behavior drifted versus the test suite

### Stage 2

Implementation truth:
- Implemented in [/Users/sjani008/SS/Meridian/stages/v2_prefilter.py](/Users/sjani008/SS/Meridian/stages/v2_prefilter.py)
- Filters by:
  - price floor
  - dollar volume floor
  - suffix exclusion
  - leveraged/inverse ETF exclusion
  - minimum bars
- Computes ADX/ATR and tags regime
- Writes `prefilter_results`

Dependencies:
- Stage 1 ready state via `cache_meta.validation_status`
- `daily_bars`
- sector map JSON

DB/table contracts:
- `prefilter_results(date,ticker,regime,price,dollar_volume,bars_available,atr_pct,adx,sector)`

Current health / blockers:
- Built and active
- Major doc mismatch: current-state doc claims Stage 2 blocks halted names and earnings-day stocks, but the code does not. Those checks currently live in Stage 6, not Stage 2.
- Takes a real DB-wide scan; not a stub
- Suitable as a reusable daily-universe stage

### Stage 3

Implementation truth:
- Implemented in [/Users/sjani008/SS/Meridian/stages/v2_factor_engine.py](/Users/sjani008/SS/Meridian/stages/v2_factor_engine.py)
- Uses five modules:
  - m1 technical core
  - m2 structural phase
  - m3 damage shortside
  - m4 mean reversion
  - m5 market context
- Loads OHLCV and latest options data, computes per-ticker rows, writes `factor_matrix_daily`
- `compute_factors()` compatibility helper does not recompute; it returns stored rows

Dependencies:
- Stage 2 output
- `daily_bars`
- sector map
- options data
- factor registry

DB/table contracts:
- `factor_matrix_daily(date,ticker,regime,<dynamic factor columns>)`
- `cache_meta` for run stats

Current health / blockers:
- Built and active
- Important mismatch: `factor_registry.json` enables 50 features, but the live factor engine maps only 31 active features that exist in the five factor modules. Enabled registry groups such as lagged returns, fundamental, sector, and time features are not produced by Stage 3.
- Known runtime inefficiency: Stage 3 can rerun prefilter inside factor engine if cache is not used
- Backfill performance bottleneck is real and centered in m1/m4

### Stage 4 / 4A / 4B

Implementation truth:
- Stage 4A:
  - [/Users/sjani008/SS/Meridian/stages/v2_training_backfill.py](/Users/sjani008/SS/Meridian/stages/v2_training_backfill.py) is real and writes `training_data`
  - [/Users/sjani008/SS/Meridian/stages/v2_fundamental_enrichment.py](/Users/sjani008/SS/Meridian/stages/v2_fundamental_enrichment.py) adds 15 fundamental/calendar columns and exports a CSV to `~/SS/NN_Sandbox/data/meridian_ALL_features.csv`
- Stage 4B inference:
  - [/Users/sjani008/SS/Meridian/stages/tcn_scorer.py](/Users/sjani008/SS/Meridian/stages/tcn_scorer.py) is real
  - [/Users/sjani008/SS/Meridian/stages/lgbm_scorer.py](/Users/sjani008/SS/Meridian/stages/lgbm_scorer.py) is real
  - model files exist under `models/tcn_pass_v1/` and `models/lgbm_pass_v1/`

Dependencies:
- `training_data`
- `factor_history`
- model artifacts on disk
- external CSV path for LGBM training script
- yfinance for fundamental enrichment

DB/table contracts:
- `training_data(date,ticker,<factors>,forward_return_5d,regime,sector,price,...)`
- `factor_history(date,ticker,<19 TCN features>)`
- `predictions_daily(date,ticker,predicted_return,regime,sector,price,top_shap_factors)`

Current health / blockers:
- This is the most important partially-built area.
- Real model inference exists, but Stage 4 in the nightly orchestrator is still mock.
- The current nightly pipeline therefore uses:
  - mock `predicted_return` for residual-alpha ranking
  - real TCN inference inside Stage 5 for `tcn_score`
- LGBM is not part of the live nightly stack.
- Formal training architecture is not self-contained:
  - there is no canonical in-repo trainer entrypoint matching the spec
  - `scripts/train_lgbm.py` depends on an external NN_Sandbox CSV path
- TCN is explicitly one-sided/bullish by design, which weakens Meridian shorts.

### Stage 5

Implementation truth:
- Implemented in [/Users/sjani008/SS/Meridian/stages/v2_selection.py](/Users/sjani008/SS/Meridian/stages/v2_selection.py)
- Loads:
  - `predictions_daily` or mock predictions
  - daily return histories for beta stripping
  - TCN scores directly from `tcn_scorer.py`
- Computes:
  - beta
  - market component
  - residual alpha
  - side-aware factor percentile
  - final blend with TCN
- Writes `shortlist_daily`

Dependencies:
- `predictions_daily`
- `daily_bars`
- TCN model for real `tcn_score`
- Stage 2 prefilter fallback for mock mode

DB/table contracts:
- `shortlist_daily(date,ticker,direction,predicted_return,beta,market_component,residual_alpha,rank,regime,sector,price,top_shap_factors,factor_rank,tcn_score,final_score,...)`

Current health / blockers:
- Built and active
- Operationally important file, with explicit “do not touch” culture around it
- Live dependency problem: if Stage 4 stays mock, then Stage 5 is only partially real
- Test suite for Stage 5 is stale and does not match current implementation names/contracts
- Schema drift exists: live `shortlist_daily` includes extra legacy UI columns such as `expected_return`, `conviction`, `alpha`

### Stage 6

Implementation truth:
- Implemented in [/Users/sjani008/SS/Meridian/stages/v2_risk_filters.py](/Users/sjani008/SS/Meridian/stages/v2_risk_filters.py)
- Reads shortlist, prefilter data, account state, and config
- Computes ATR-based sizing and applies filters
- Writes:
  - `tradeable_portfolio`
  - `portfolio_state`
  - `trade_log` schema

Dependencies:
- `shortlist_daily`
- `prefilter_results`
- `risk_config.json`
- optional yfinance earnings lookup

DB/table contracts:
- `tradeable_portfolio`
- `portfolio_state`
- `trade_log`

Current health / blockers:
- Built and active
- Major strategic mismatch:
  - Meridian selection/forward-tracker is a 5-day swing system
  - Stage 6 has been moved toward TTP Day Trade rules with EOD closure and no-new-trades-after intraday logic
- Major runtime default mismatch:
  - code default `DEFAULT_PROP_FIRM` is `trade_the_pool_day_50k`
  - but orchestrator CLI default is still `--prop-firm ftmo`
  - live `portfolio_state` rows currently show `account_balance = 100000`, consistent with FTMO defaults, not TTP 50K
- UI is also still FTMO-biased, which amplifies this mismatch

### Stage 7

Implementation truth:
- Implemented in:
  - [/Users/sjani008/SS/Meridian/stages/v2_orchestrator.py](/Users/sjani008/SS/Meridian/stages/v2_orchestrator.py)
  - [/Users/sjani008/SS/Meridian/stages/v2_api_server.py](/Users/sjani008/SS/Meridian/stages/v2_api_server.py)
  - [/Users/sjani008/SS/Meridian/stages/v2_forward_tracker.py](/Users/sjani008/SS/Meridian/stages/v2_forward_tracker.py)
- Orchestrator is a real CLI stage runner with per-stage logs and Telegram summary
- API is a real FastAPI server with read and execution-ish endpoints
- Forward tracker is a real post-pick evaluation layer

Dependencies:
- all stage tables
- `.env`
- FastAPI/uvicorn
- Alpaca paper keys for trade endpoints

DB/table contracts:
- `orchestrator_log`
- `cache_meta`
- `pick_tracking`

Current health / blockers:
- Built and active
- Orchestrator is not fully canonical to the intended ML architecture because Stage 4 is still mock
- API health/model endpoints present a simplified view that can be misleading:
  - `/api/model/health` reports `MOCK` if any stage logged `MOCK`
  - that means the UI can report fallback/mock status even while Stage 5 is actually using real TCN inference
- Forward tracker is real for 5-day validation, which conflicts with the current day-trade Stage 6 direction

## 5. React app audit

### Current structure

App structure:
- Routes:
  - `/` dashboard
  - `/candidates`
  - `/trades`
  - `/model`
  - `/settings`
- Shell:
  - fixed nav/sidebar in [/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx](/Users/sjani008/SS/Meridian/ui/signalstack-app/components/app-shell.tsx)
- Data layer:
  - single API adapter file in [/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts](/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/api.ts)
  - typed frontend view models in [/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/mock-data.ts](/Users/sjani008/SS/Meridian/ui/signalstack-app/lib/mock-data.ts)

Data-fetching pattern:
- client-side fetching with `useEffect`
- one central `request()` wrapper
- adapter functions transform snake_case API payloads to UI types
- silent empty-state fallback on API failures for most pages
- API base resolution:
  - `NEXT_PUBLIC_API_URL` if set
  - localhost if browser hostname is localhost
  - otherwise demo/no-URL mode

### Current strengths

- The shell is already generic enough in navigation and page layout to host more than one lane.
- The app has one centralized API layer instead of scattered fetch calls.
- Pages are decently segmented by concern:
  - dashboard
  - candidates
  - trades
  - model/tracking
  - settings
- It is already deployed and appears to be used as an operator console, not just a prototype.

### Current weaknesses

- The app is still Meridian-specific in both data model and UX language.
- `lib/api.ts` and `mock-data.ts` encode one lane’s assumptions everywhere:
  - `Candidate`
  - `PortfolioState`
  - `ModelHealth`
  - `TrackingSummary`
- `adaptPortfolioState()` hardcodes FTMO-style loss/drawdown assumptions and challenge labels, which conflicts with current Stage 6 TTP direction.
- `model-client.tsx` labels raw sample factor rows from `/api/model/factors` as “Factor Importance,” but the backend endpoint actually returns a single row from `factor_matrix_daily`, not feature importance output.
- Several components still depend on mock defaults:
  - `candidate-detail-panel` starts from `mockTickerInfo`
  - API failures often resolve to empty/neutral UI state rather than explicit operator error
- The repo includes build artifacts and `node_modules`, which will confuse future build agents and code review.

### Suitability as unified SignalStack shell

Yes, conditionally.

Why it is a plausible shell:
- the navigation and layout are already generic enough
- the data adapter layer is centralized
- the app is already a multi-page operator console rather than a single-lane landing page

Why it is not ready as-is:
- current API contracts are Meridian-native, not lane-agnostic
- the app has no notion of “lane” in routing, state, or types
- several views are tightly coupled to Meridian fields like `residual_alpha`, `tcn_score`, `factor_rank`
- settings/portfolio cards are currently incorrect for non-FTMO/non-Meridian runtime assumptions

### Best integration points for S1

Cleanest fit based on current structure:
- new sibling pages/routes for S1 morning/evening intelligence and scorer/convergence views
- the current `/candidates` and `/model` patterns are the most natural templates

Reason:
- S1 is more of a scan/reporting lane than an execution lane
- the current candidates/model pages already express ranked-signal and model-health concepts

Constraint:
- S1 should not be forced through Meridian candidate types. It needs its own API adapters and lane-specific types.

### Best integration points for Vanguard

Cleanest fit based on current structure:
- `/trades`
- `/settings`
- possibly a new execution/portfolio route group adjacent to trades

Reason:
- Vanguard is the natural execution/intraday lane
- Meridian UI already has positions, trades, risk sizing, and broker-oriented API endpoints as the closest conceptual fit

Constraint:
- the current trade APIs are Meridian+Alpaca paper specific and not a clean execution abstraction yet

## 6. Cross-cutting issues

### Repo structure

- The repo has real code but also substantial noise:
  - `node_modules/`
  - `.next/`
  - `output/`
  - backup files
  - stale docs
- `stages/` mixes runtime entrypoints, model scorers, research backfill, and enrichment scripts in one folder.
- There is doc drift between root docs, `docs/`, and “Implementation Docs”.
- For future build agents, this repo is understandable but not clean.

### Config / env

- `.env` is loaded directly by both orchestrator and API server.
- `factor_registry.json` presents a larger active feature universe than Stage 3 actually computes.
- `risk_config.json` is real and multi-preset, but runtime defaults across code, docs, and UI are inconsistent.
- UI API base behavior still depends on Vercel env var or localhost detection; otherwise it falls into demo/no-URL mode.

### DB / schema contracts

- `v2_universe.db` is the real system DB.
- Table contracts are mostly additive and pragmatic, but there is schema drift:
  - `shortlist_daily` has extra legacy columns
  - `predictions_daily` stores mock/legacy Stage 4 schema rather than a richer canonical ML schema
  - `factor_history` only stores TCN feature subset, not full factor matrix history
- Stage 4A enrichment adds fundamental and calendar columns to `training_data`, but those are not part of live Stage 3 runtime production.

### Orchestration / entrypoints

Canonical runtime entrypoints:
- `python3 stages/v2_orchestrator.py`
- `python3 stages/v2_api_server.py`
- `python3 stages/v2_forward_tracker.py ...`
- `npm run dev|build|start` for UI

But operational automation is not self-contained in the repo:
- current-state doc references external scripts in `~/SS`
- launchd/plist schedule docs live in specs, not in repo automation files

### Model / training state

- Meridian has real model artifacts.
- The nightly runtime still treats Stage 4 as mock.
- TCN is used live inside Stage 5.
- LGBM exists but is offline/research-only from the nightly runtime’s perspective.
- Training pipeline is not fully repo-native:
  - external CSV path dependency
  - no canonical Stage 4B trainer entrypoint

### API / UI coupling

- API/UI coupling is direct and relatively tight.
- The UI types and adapters are written around Meridian-specific endpoint shapes.
- `/api/model/health` and `/api/model/factors` do not fully support what the UI labels imply.
- This is acceptable for a single-lane internal console, but weak for a unified multi-lane product shell.

### Spec mismatches

Important mismatches between specs/docs and code:
- docs say 20+20 selection; live code does 30+30
- docs say FTMO in places; Stage 6 code defaults to TTP but orchestrator still defaults to FTMO
- docs imply Stage 2 blocks halted/earnings; code does not
- docs imply full Stage 4B trainer exists; code does not
- factor registry implies 50 active features; live Stage 3 computes 31 mapped features
- UI settings/portfolio still present FTMO assumptions even when risk config is TTP-oriented

## 7. Severity summary

### Blockers

- Stage 4 is still mock in the live orchestrator. This is the single biggest blocker to calling Meridian a truly complete ML production lane.
- Stage 6 risk direction is internally inconsistent with the rest of the system:
  - 5-day swing selection/forward tracking
  - day-trade TTP risk rules and EOD cutoffs
- Runtime defaults are inconsistent:
  - `v2_risk_filters.py` defaults to TTP 50K
  - `v2_orchestrator.py` still defaults to `ftmo`
  - live `portfolio_state` rows currently reflect FTMO-style 100K
- Test suite is not green. `pytest` currently fails in Stage 1, Stage 5, Stage 6, and orchestrator-related tests.

### Should fix soon

- Make Stage 4 canonical:
  - explicit real scoring path
  - explicit model registry/version metadata
  - stop writing mock `predictions_daily` in normal operation
- Reconcile risk/system timeframe:
  - either commit Meridian to swing
  - or split swing research from day-trade execution
- Clean factor registry/runtime mismatch:
  - clearly separate live runtime features from training-only enrichments
- Fix UI contract drift:
  - remove FTMO hardcoding in `lib/api.ts`
  - stop calling raw factor rows “feature importance”
- Remove source-tree noise:
  - `node_modules`
  - `.next`
  - backup files
  - stale docs or at least mark them stale

### Ignore for now

- Zero-byte package/internal `__init__.py` files
- old standalone HTML dashboard file
- old backfill logs and stale generated artifacts in `data/`
- minor yfinance/delisted warning noise in Stage 1

## 8. Merger recommendation

### Should Meridian become the primary product shell? YES/NO

YES, with conditions.

Reason:
- Meridian already has the strongest product-shell candidate:
  - real API
  - real React app
  - real candidate / model / trades / settings pages
  - real shared DB-backed runtime
- S1 is still stronger as a signal research/reporting lane in some areas, but Meridian is the cleaner place to host a multi-lane operator product.
- Vanguard is not yet a better shell candidate based on current build state described in the parallel audit.

But:
- Meridian should become the shell, not the unquestioned logic owner.
- Today it is still too Meridian-specific in both data contracts and UI assumptions.

### Recommended transition plan

1. Treat Meridian as the UI/API shell and lane host.
- Keep Meridian’s React app as the front-end base.
- Add lanes instead of forcing S1/Vanguard through Meridian-native types.

2. Stabilize Meridian’s own canonical contracts first.
- fix Stage 4 mock/live ambiguity
- reconcile Stage 6 timeframe/risk direction
- align UI/API/runtime defaults

3. Merge S1 as a strategy/reporting lane, not as a hidden rewrite of Meridian.
- S1 should contribute:
  - scorer insights
  - convergence/morning intelligence
  - possibly short-side confirmation logic
- It should enter as separate endpoints/pages or a lane namespace, not by mutating Meridian candidate schema in place

4. Merge Vanguard as the execution/intraday lane later.
- Best fit is on the trades/execution side of the shell
- Do not mix its intraday execution assumptions into Meridian’s daily swing lane prematurely

### Recommended next build order

1. Make Meridian internally coherent.
- real Stage 4 live path
- consistent risk default and timeframe
- green critical tests

2. Clean the shell.
- remove repo noise
- normalize API responses
- fix UI contract drift and FTMO hardcoding

3. Add S1 as a second lane.
- reporting/scorer/convergence first
- avoid direct model/code transplant until shell contracts are stable

4. Add Vanguard after shell contracts are lane-aware.
- positions/execution/account/trade controls are the natural integration point

5. Only then consider deeper model or orchestrator consolidation across repos.

