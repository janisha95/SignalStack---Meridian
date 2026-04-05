# Unified Candidate Source Investigation

## 1. Files / tables / endpoints reviewed

Advance / S1:
- `/Users/sjani008/SS/Advance/S1_ARCHITECTURE.md`
- `/Users/sjani008/SS/Advance/s1_pass_scorer.py`
- `/Users/sjani008/SS/Advance/s1_morning_report_v2.py`
- `/Users/sjani008/SS/Advance/data_cache/signalstack_results.db`
  - `evening_pass`
  - `scorer_predictions`
  - `convergence_picks`
  - `morning_decisions`
- `/Users/sjani008/SS/Advance/data_cache/s1_forward_tracking.db`
  - `candidate_journal`
- `/Users/sjani008/SS/Advance/data_cache/s1_standings.db`
  - `standings`
- `/Users/sjani008/SS/Advance/evening_results/convergence_20260329_1716.json`
- `/Users/sjani008/SS/Advance/evening_results/evening_report_v2_20260329_1716.json`
- `/Users/sjani008/SS/Advance/morning_results/morning_v2_20260329_1622.json`

Meridian:
- `/Users/sjani008/SS/Meridian/stages/v2_selection.py`
- `/Users/sjani008/SS/Meridian/stages/v2_risk_filters.py`
- `/Users/sjani008/SS/Meridian/stages/v2_api_server.py`
- `/Users/sjani008/SS/Meridian/stages/v2_forward_tracker.py`
- `/Users/sjani008/SS/Meridian/stages/lgbm_scorer.py`
- `/Users/sjani008/SS/Meridian/docs/STAGE_5_COMPLETE_SPEC.md`
- `/Users/sjani008/SS/Meridian/MERIDIAN_CURRENT_STATE.md`
- `/Users/sjani008/SS/Meridian/data/v2_universe.db`
  - `shortlist_daily`
  - `tradeable_portfolio`
  - `portfolio_state`
  - `predictions_daily`
  - `pick_tracking`

Vanguard:
- `/Users/sjani008/SS/Vanguard/VANGUARD_AGENTS.md`
- `/Users/sjani008/SS/Vanguard/docs/VANGUARD_SUPPORTING_SPECS.md`
- `/Users/sjani008/SS/Vanguard/docs/VANGUARD_STAGE_V7_1_EXECUTOR_SPEC.md`
- `/Users/sjani008/SS/Vanguard/scripts/execute_daily_picks.py`
- `/Users/sjani008/SS/Vanguard/stages/vanguard_prefilter.py`
- `/Users/sjani008/SS/Vanguard/stages/vanguard_factor_engine.py`
- `/Users/sjani008/SS/Vanguard/stages/vanguard_selection.py`
- `/Users/sjani008/SS/Vanguard/stages/vanguard_risk_filters.py`
- `/Users/sjani008/SS/Vanguard/stages/vanguard_orchestrator.py`
- `/Users/sjani008/SS/Vanguard/data/vanguard_universe.db`
  - `vanguard_bars_5m`
  - `vanguard_health`
  - `vanguard_features`
  - `vanguard_execution_log`

Relevant endpoints:
- S1 runtime architecture doc:
  - `POST /analyze/bulk`
  - `POST /ml/predict`
- Meridian API:
  - `GET /api/candidates`
  - `GET /api/positions`
  - `GET /api/v2/scan`
- Vanguard:
  - no native candidate API found

## 2. Candidate-producing sources by lane

### S1 / Advance

#### Source A: `signalstack_results.db.evening_pass`
- Type: SQLite table
- Operational role: upstream persisted PASS/BLOCK row capture for evening/night scans
- Producer: evening/night scan pipeline before scorer/convergence layers
- True status: real operational source, but not the final ranked source used by reports/execution
- Why it matters:
  - this is the broadest persisted candidate row set
  - includes PASS/BLOCK/NO_MODEL-style gating context
- Why it is not the best unified-table source:
  - it is pre-scorer and pre-convergence
  - downstream consumers do not use it directly as the final shortlist

#### Source B: `signalstack_results.db.scorer_predictions`
- Type: SQLite table
- Operational role: canonical scored candidate surface for S1 daily picks
- Producer: `s1_pass_scorer.py`
- True status: real operational source
- Evidence:
  - `scripts/execute_daily_picks.py` reads this table directly
  - `s1_morning_report_v2.py` loads from this table
- Why it matters:
  - this is the strongest persisted S1 candidate-ranking surface today
  - it contains `scorer_prob` plus base gate fields

#### Source C: `evening_results/convergence_*.json`
- Type: JSON artifact
- Operational role: convergence-ranked shortlist and synthesis artifact
- Producer: S1 convergence pipeline
- True status: real operational source
- Evidence:
  - `scripts/execute_daily_picks.py` reads latest `convergence_*.json`
  - `s1_morning_report_v2.py` prefers latest convergence JSON and falls back to DB
- Why it matters:
  - this is where `convergence_score` and convergence shortlist membership are richest today
  - JSON holds more shortlist-level context than the DB mirror

#### Source D: `signalstack_results.db.convergence_picks`
- Type: SQLite table
- Operational role: DB mirror of convergence shortlist
- True status: real, but secondary to convergence JSON when both exist
- Why it matters:
  - useful for DB-side joins and normalization
- Why it is secondary:
  - `s1_morning_report_v2.py` explicitly prefers JSON first
  - the JSON shortlist has richer fields

#### Source E: `signalstack_results.db.morning_decisions`
- Type: SQLite table
- Operational role: post-candidate morning go/no-go overlay
- True status: downstream decision layer, not a candidate-producing source
- Should not be treated as the unified candidate base

#### Not primary candidate sources
- `data_cache/s1_standings.db.standings`
  - mirror/telemetry for standings/intelligence
- `data_cache/s1_forward_tracking.db.candidate_journal`
  - forward-tracker capture, not candidate generation
- `POST /analyze/bulk`
  - live runtime producer, but ephemeral request output, not the canonical persisted daily shortlist surface

#### S1 operational truth
- For persisted, rankable S1 candidates today, the true sources are:
  - `scorer_predictions`
  - latest `convergence_*.json`
- `evening_pass` is the upstream base candidate pool

### Meridian

#### Source A: `v2_universe.db.shortlist_daily`
- Type: SQLite table
- Operational role: canonical daily candidate table
- Producer: `stages/v2_selection.py`
- True status: primary operational source
- Evidence:
  - `v2_api_server.py` `GET /api/candidates` reads `shortlist_daily`
  - `scripts/execute_daily_picks.py` in Vanguard reads `shortlist_daily`
  - `v2_forward_tracker.py` captures from `shortlist_daily`
- Why it matters:
  - this is Meridian’s true candidate table today
  - it is the cleanest candidate source of the three lanes

#### Source B: `v2_universe.db.tradeable_portfolio`
- Type: SQLite table
- Operational role: risk-filtered approved positions
- Producer: `stages/v2_risk_filters.py`
- True status: operational, but this is an approved-position output, not the raw candidate table
- Evidence:
  - `v2_api_server.py` `GET /api/positions` reads `tradeable_portfolio`
- Why it matters:
  - if the unified table wants “approved/ready-to-trade” rows, this is Meridian’s downstream source
  - if the unified table wants “candidate universe,” this is too late in the pipeline

#### Source C: `v2_universe.db.predictions_daily`
- Type: SQLite table
- Operational role: upstream model score input to Stage 5
- Producer: Stage 4 / 4B scoring layer
- True status: upstream, not the final candidate source
- Why it matters:
  - useful if the future unified table ever wants pre-selection model outputs
  - not the right candidate source for product-level candidate views

#### Source D: `GET /api/candidates`
- Type: API endpoint
- Operational role: UI-facing candidate surface
- True status: real operational endpoint, but it is a filtered projection of `shortlist_daily`
- Important incompatibility:
  - the table contains `expected_return`, `conviction`, and `alpha`
  - the endpoint currently does not return them
  - `_normalize_candidate_rows()` returns only:
    - `ticker`
    - `direction`
    - `predicted_return`
    - `residual_alpha`
    - `beta`
    - `regime`
    - `sector`
    - `price`
    - `rank`
    - `factor_rank`
    - `tcn_score`
    - `final_score`
    - `top_shap_factors`

#### Meridian operational truth
- For candidate normalization, Meridian’s true source is `shortlist_daily`
- `/api/candidates` is a UI projection and is currently lossy relative to the table

### Vanguard

#### Source A: native Vanguard shortlist
- Intended names from spec:
  - `vanguard_shortlist`
  - `vanguard_tradeable_portfolio`
- True status: missing completely in the live DB
- Evidence:
  - live `vanguard_universe.db` tables are only:
    - `vanguard_bars_5m`
    - `vanguard_health`
    - `vanguard_features`
    - `vanguard_execution_log`
  - `stages/vanguard_selection.py` is zero bytes
  - `stages/vanguard_risk_filters.py` is zero bytes
  - `stages/vanguard_orchestrator.py` is zero bytes

#### Source B: `vanguard_health`
- Type: SQLite table
- Operational role: prefilter/health status per symbol
- Producer: `stages/vanguard_prefilter.py`
- True status: real, but not a candidate table
- Why it matters:
  - this is status/eligibility, not a shortlist

#### Source C: `vanguard_features`
- Type: SQLite table
- Operational role: factor-engine feature blob per symbol and cycle
- Producer: `stages/vanguard_factor_engine.py`
- True status: real, but not a candidate table
- Why it matters:
  - candidate-like only in the sense that it contains scored inputs
  - there is no native selection output built from it yet

#### Source D: `vanguard_execution_log`
- Type: SQLite table
- Operational role: execution / forward-tracked order log
- Producer: execution bridge
- True status: real, but this is execution history, not native candidate generation
- Important truth:
  - current rows are from external daily lanes, mainly Meridian
  - sample live rows are `source_system='meridian'`

#### Source E: `scripts/execute_daily_picks.py`
- Type: script-level candidate ingestion and tiering
- Operational role: current practical “candidate consumer” in Vanguard
- Reads:
  - S1 `scorer_predictions`
  - latest S1 `convergence_*.json`
  - Meridian `shortlist_daily`
- Produces:
  - tiered in-memory pick dicts
  - `TradeOrder` objects with `signal_tier` and `signal_metadata`
  - `vanguard_execution_log` writes
- True status:
  - operational today
  - but not native Vanguard intraday candidate generation

#### Vanguard operational truth
- Vanguard does not have a native intraday candidate table today
- The only real current candidate-like pipeline is:
  - external S1 / Meridian picks
  - tiered in `execute_daily_picks.py`
  - logged as execution rows

## 3. Exact field inventory

### S1 fields

#### `evening_pass`
Table:
- `signalstack_results.db.evening_pass`

Columns:
- `id`
- `run_date`
- `run_type`
- `ticker`
- `strategy`
- `direction`
- `row_status`
- `ml_decision`
- `p_tp`
- `nn_p_tp`
- `gate_source`
- `edge_score`
- `regime`
- `price`
- `atr_pct`
- `model_slot`
- `threshold`
- `created_at`
- `sector`
- `run_id`

Required by schema:
- `run_date`
- `run_type`
- `ticker`
- `strategy`
- `created_at`
- `run_id`

Often optional / null in live rows:
- `nn_p_tp`
- `edge_score`
- `price`
- `atr_pct`
- `model_slot`
- `sector`

Latest run null hints:
- latest `night_20260329_1716` batch had:
  - `nn_p_tp`: 1 null
  - `edge_score`: 11 null
  - `price`: 7 null
  - `atr_pct`: 12 null
  - `model_slot`: 6 null
  - `sector`: 12 null

Sample row shape:
- `{run_date, run_type, run_id, ticker, strategy, direction, row_status, ml_decision, p_tp, nn_p_tp, gate_source, regime, threshold, created_at, ...}`

#### `scorer_predictions`
Table:
- `signalstack_results.db.scorer_predictions`

Columns:
- `id`
- `run_date`
- `ticker`
- `direction`
- `strategy`
- `p_tp`
- `nn_p_tp`
- `gate_source`
- `scorer_prob`
- `scorer_rank`
- `regime`
- `price`
- `created_at`
- `sector`

Required by schema:
- `run_date`
- `ticker`
- `created_at`

Operationally expected / almost always populated:
- `direction`
- `strategy`
- `p_tp`
- `gate_source`
- `scorer_prob`
- `scorer_rank`
- `regime`
- `sector`

Often optional / null:
- `nn_p_tp`
- `price`

Latest date null hints:
- `nn_p_tp`: 9 null
- `price`: 32 null

Sample row shape:
- `{run_date, ticker, direction, strategy, p_tp, nn_p_tp, gate_source, scorer_prob, scorer_rank, regime, price, sector, created_at}`

#### `convergence_picks`
Table:
- `signalstack_results.db.convergence_picks`

Columns:
- `id`
- `run_date`
- `rank`
- `ticker`
- `direction`
- `strategies`
- `convergence_score`
- `strategy_strength`
- `n_agree`
- `regime`
- `p_tp`
- `nn_p_tp`
- `gate_source`
- `tradeable`
- `srs_multiplier`
- `options_multiplier`
- `price`
- `created_at`
- `run_id`

Required by schema:
- `run_date`
- `ticker`
- `created_at`
- `run_id`

Optional:
- nearly everything else besides `run_date/ticker/created_at/run_id`

#### `convergence_*.json` shortlist item
Latest artifact examined:
- `convergence_20260329_1716.json`

Shortlist item keys:
- `avg_score`
- `convergence_score`
- `dead_band_reason`
- `direction`
- `earnings_date`
- `earnings_days`
- `earnings_risk`
- `gate_source`
- `has_conflict`
- `n_agree`
- `nn_decision`
- `nn_p_tp`
- `options_flow`
- `options_multiplier`
- `p_tp`
- `regime`
- `rel_volume`
- `sources`
- `srs_flow`
- `srs_multiplier`
- `strategies`
- `strategy_strength`
- `ticker`
- `tradeable`

This is the richest current S1 shortlist payload.

#### `morning_decisions`
Table:
- `signalstack_results.db.morning_decisions`

Columns:
- `id`
- `run_date`
- `ticker`
- `direction`
- `go`
- `news_reason`
- `risk_flags`
- `convergence_score`
- `created_at`

This is a downstream overlay, not a source candidate table.

### Meridian fields

#### `shortlist_daily`
Table:
- `v2_universe.db.shortlist_daily`

Columns:
- `date`
- `ticker`
- `direction`
- `predicted_return`
- `beta`
- `market_component`
- `residual_alpha`
- `rank`
- `regime`
- `sector`
- `price`
- `top_shap_factors`
- `factor_rank`
- `tcn_score`
- `final_score`
- `expected_return`
- `conviction`
- `alpha`

Required by schema:
- `date`
- `ticker`
- `direction`

Live optional / often null:
- `sector`
- `top_shap_factors`
- `expected_return`
- `conviction`
- `alpha`

Latest date null hints:
- `sector`: 48 null
- `top_shap_factors`: 60 null
- `expected_return`: 60 null
- `conviction`: 60 null
- `alpha`: 60 null

Important truth:
- the newer Stage 5 fields exist in schema but are not fully populated in live rows

Sample row shape:
- `{date, ticker, direction, predicted_return, beta, market_component, residual_alpha, rank, regime, sector, price, factor_rank, tcn_score, final_score, expected_return, conviction, alpha, top_shap_factors}`

#### `tradeable_portfolio`
Table:
- `v2_universe.db.tradeable_portfolio`

Columns:
- `date`
- `ticker`
- `direction`
- `shares`
- `entry_price`
- `stop_price`
- `tp_price`
- `risk_dollars`
- `risk_pct`
- `position_value`
- `atr`
- `sector`
- `rank`
- `residual_alpha`
- `filter_status`
- `regime`
- `predicted_return`
- `beta`
- `filter_reason`

Required by schema:
- `date`
- `ticker`

Operational meaning:
- this is an approved / rejected risk-filtered table, not just candidates

Sample live shape:
- many rows currently show `shares=0` and `filter_status='REJECTED'` with `filter_reason='LOW_VOLUME'`

#### `predictions_daily`
Table:
- `v2_universe.db.predictions_daily`

Columns:
- `date`
- `ticker`
- `predicted_return`
- `regime`
- `sector`
- `price`
- `top_shap_factors`

Required by schema:
- `date`
- `ticker`

Operational meaning:
- model output table, upstream of candidate selection

#### `/api/candidates` projection
Actual returned fields from `_normalize_candidate_rows()`:
- `ticker`
- `direction`
- `predicted_return`
- `residual_alpha`
- `beta`
- `regime`
- `sector`
- `price`
- `rank`
- `factor_rank`
- `tcn_score`
- `final_score`
- `top_shap_factors`

Important omission:
- `expected_return`
- `conviction`
- `alpha`

### Vanguard fields

#### Native intraday candidate fields
- No native candidate table exists today.
- `vanguard_shortlist` and `vanguard_tradeable_portfolio` are spec-only, not live.

#### `vanguard_health`
Table:
- `vanguard_universe.db.vanguard_health`

Columns:
- `symbol`
- `cycle_ts_utc`
- `status`
- `relative_volume`
- `spread_bps`
- `bars_available`
- `last_bar_ts_utc`

Required by schema:
- `symbol`
- `cycle_ts_utc`

Operational meaning:
- health / eligibility row, not a candidate row

#### `vanguard_features`
Table:
- `vanguard_universe.db.vanguard_features`

Columns:
- `symbol`
- `cycle_ts_utc`
- `features_json`

Required by schema:
- `symbol`
- `cycle_ts_utc`

Current feature JSON keys observed:
- `atr_expansion`
- `daily_adx`
- `daily_drawdown_from_high`
- `gap_pct`
- `momentum_12bar`
- `momentum_3bar`
- `momentum_acceleration`
- `premium_discount_zone`
- `session_opening_range_position`
- `session_vwap_distance`

Operational meaning:
- factor/feature blob, not a candidate row

#### `vanguard_execution_log`
Table:
- `vanguard_universe.db.vanguard_execution_log`

Columns:
- `id`
- `cycle_ts_utc`
- `account_id`
- `symbol`
- `direction`
- `action`
- `shares_or_lots`
- `order_type`
- `limit_price`
- `stop_price`
- `fill_price`
- `fill_quantity`
- `execution_bridge`
- `bridge_order_id`
- `status`
- `error_message`
- `latency_ms`
- `source_system`
- `created_at_utc`

Required by schema:
- `cycle_ts_utc`
- `account_id`
- `symbol`
- `direction`
- `action`

Operational meaning:
- execution / forward-tracked order log
- current sample rows are imported from Meridian, not native Vanguard candidates

#### `execute_daily_picks.py` in-memory pick dicts
S1 pick dict fields:
- `ticker`
- `direction`
- `signal_tier`
- `p_tp`
- `nn_p_tp`
- `scorer_prob`
- `convergence_score`
- `price`
- `regime`
- `gate_source`

Meridian pick dict fields:
- `ticker`
- `direction`
- `signal_tier`
- `tcn_score`
- `factor_rank`
- `final_score`
- `price`
- `regime`

These are real candidate-like objects in Vanguard today, but they are not persisted as a candidate table.

## 4. Score / output semantics

### S1 score meanings

- `p_tp`
  - lane: S1
  - meaning: RF / ML gate probability of TP hit under the gate model used for that strategy/slot
  - comparable across lanes: no
  - unified-column status: lane-specific metadata

- `nn_p_tp`
  - lane: S1
  - meaning: neural / NN probability of TP hit where applicable
  - comparable across lanes: no
  - unified-column status: lane-specific metadata

- `scorer_prob`
  - lane: S1
  - meaning: post-PASS LightGBM scorer probability used to rank PASS rows
  - operationally the best persisted S1 ranking score today
  - comparable across lanes: no
  - unified-column status: candidate for `primary_score` within S1 only

- `convergence_score`
  - lane: S1
  - meaning: blended agreement / strategy-strength score from convergence pipeline
  - comparable across lanes: no
  - unified-column status: lane-specific metadata

- `strategy_strength`
  - lane: S1
  - meaning: strength contribution from constituent strategy outputs inside convergence
  - comparable across lanes: no
  - unified-column status: metadata

- `n_agree`
  - lane: S1
  - meaning: number of strategies agreeing on the directional idea
  - comparable across lanes: partly as “agreement count,” but semantically still S1-specific
  - unified-column status: metadata, not core

- `gate_source`
  - lane: S1
  - meaning: which gating engines agreed, such as `RF_ONLY`, `NN_ONLY`, `BOTH`
  - comparable across lanes: no
  - unified-column status: metadata

- `tradeable`
  - lane: S1 convergence artifact
  - meaning: shortlist-level flag for whether the converged idea should be treated as tradeable
  - comparable across lanes: only loosely
  - unified-column status: maybe normalize to a generic `status`, but keep source detail in metadata

- `edge_score`
  - lane: S1 upstream PASS rows
  - meaning: strategy-specific edge component from upstream scan
  - comparable across lanes: no
  - unified-column status: metadata

### Meridian score meanings

- `predicted_return`
  - lane: Meridian
  - meaning today: Stage 5 output field retained for backward compatibility; in practice it is the candidate-level expected-return style score used downstream by Stage 6
  - comparable across lanes: not safely
  - unified-column status: lane-specific metadata, not a global shared score

- `tcn_score`
  - lane: Meridian
  - meaning: TCN model probability-style score used in ranking
  - comparable across lanes: no
  - unified-column status: metadata

- `factor_rank`
  - lane: Meridian
  - meaning: factor percentile/rank within Meridian ranking flow
  - comparable across lanes: no
  - unified-column status: metadata

- `final_score`
  - lane: Meridian
  - meaning: current Stage 5 ranking score written to shortlist and used for ordering
  - operationally the best live ranking field for Meridian today
  - comparable across lanes: no
  - unified-column status: candidate for `primary_score` within Meridian only

- `residual_alpha`
  - lane: Meridian
  - meaning: market-adjusted alpha/residual signal; sign also carries direction meaning in the newer Stage 5 spec
  - comparable across lanes: no
  - unified-column status: metadata

- `expected_return`
  - lane: Meridian
  - meaning: intended explicit expected return field from newer Stage 5 contract
  - live truth: schema exists but values are null in current rows
  - unified-column status: not safe for normalization yet

- `alpha`
  - lane: Meridian
  - meaning: intended explicit alpha field from newer Stage 5 contract
  - live truth: schema exists but values are null in current rows
  - unified-column status: not safe for normalization yet

- `conviction`
  - lane: Meridian
  - meaning: intended confidence scaling field from newer Stage 5 contract
  - live truth: schema exists but values are null in current rows
  - unified-column status: not safe for normalization yet

- `beta`
  - lane: Meridian
  - meaning: market beta used in alpha decomposition
  - comparable across lanes: only if another lane explicitly uses market beta in the same way, which S1 and current Vanguard do not
  - unified-column status: metadata

### Vanguard score meanings

- `status` in `vanguard_health`
  - lane: Vanguard
  - meaning: prefilter / health state such as `ACTIVE`, `LOW_VOLUME`, `STALE`, `HALTED`
  - comparable across lanes: only as health, not as candidate score
  - unified-column status: metadata / health overlay

- `relative_volume`, `spread_bps`, `bars_available`
  - lane: Vanguard
  - meaning: prefilter/market-quality diagnostics
  - comparable across lanes: partly, but not as candidate ranking
  - unified-column status: metadata

- feature JSON values in `vanguard_features`
  - lane: Vanguard
  - meaning: intraday feature-engine output
  - comparable across lanes: no
  - unified-column status: metadata only

- `signal_tier` in `execute_daily_picks.py`
  - lane: Vanguard bridge, but sourced from external daily systems
  - meaning: tier label used to categorize imported S1/Meridian signals before execution
  - comparable across lanes: not as a pure score
  - unified-column status: metadata

There is no native Vanguard intraday ranking score persisted today.

## 5. Identity / dedupe / run-key investigation

### S1

Persisted batch identifiers:
- `run_date`
- `run_type`
- `run_id`
- `created_at`

Row identity today:
- `evening_pass`
  - physical PK: `id`
  - practical batch key: `run_id`
  - no uniqueness constraint on `(run_id, ticker, direction, strategy)`
- `scorer_predictions`
  - physical PK: `id`
  - no `run_id`
  - no uniqueness constraint on `(run_date, ticker, direction, strategy)`
  - consumers dedupe by query
- `convergence_picks`
  - physical PK: `id`
  - practical batch key: `run_id`
  - no uniqueness constraint on `(run_id, ticker, direction)`
- `candidate_journal`
  - physical PK: `candidate_id`
  - this is a tracker ID, not a reusable candidate key

How ticker + direction + date is represented:
- `ticker`, `direction`, `run_date`
- but `run_type` and `run_id` are also needed to distinguish evening vs night and reruns

How duplicates are handled today:
- `scorer_predictions`
  - deduped by query using `GROUP BY ticker, direction` and `MAX(scorer_prob)`
- `s1_morning_report_v2.py`
  - dedupes loaded rows in memory
- `execute_daily_picks.py`
  - dedupes S1 scorer rows by `(ticker, direction)` and `MAX(scorer_prob)`

Practical S1 stable key today:
- best available normalized key is:
  - `(run_date, run_type or inferred batch, ticker, direction, strategy)`
- but `scorer_predictions` lacks `run_type/run_id`, which is a real identity weakness

### Meridian

Persisted identifiers:
- `date`
- `ticker`
- `direction`
- `rank`

Actual primary keys:
- `shortlist_daily`: `PRIMARY KEY (date, ticker)`
- `tradeable_portfolio`: `PRIMARY KEY (date, ticker)`
- `pick_tracking`: `PRIMARY KEY (pick_date, ticker)`

Important truth:
- direction is not part of the primary key in these tables
- this assumes one ticker cannot appear both long and short on the same date

How duplicates/reruns are handled:
- Stage 5 deletes existing `shortlist_daily` rows for the date and reinserts
- Stage 6 deletes existing `tradeable_portfolio` rows for the date and reinserts
- `pick_tracking` uses `INSERT OR IGNORE` for `(pick_date, ticker)`

Practical Meridian stable key today:
- `(date, ticker)`
- `direction` is still semantically important, but not needed to make the row unique in the current design

### Vanguard

Native candidate keys:
- none, because there is no native candidate table yet

Persisted cycle/session identifiers that exist:
- `cycle_ts_utc` in `vanguard_health`
- `cycle_ts_utc` in `vanguard_features`
- `cycle_ts_utc` in `vanguard_execution_log`

Current practical keys:
- `vanguard_health`: `(symbol, cycle_ts_utc)`
- `vanguard_features`: `(symbol, cycle_ts_utc)`
- `vanguard_execution_log`: autoincrement `id`, with `cycle_ts_utc + symbol + direction + account_id` functioning as a practical grouping key

Ticker + direction + date/session representation:
- `symbol`
- `direction`
- `cycle_ts_utc`

How duplicates are handled:
- health/features use composite PKs at the cycle level
- execution log does not dedupe; it appends events

Practical Vanguard stable key today:
- for any future native candidate table, nothing stable exists yet
- for current candidate-like execution imports, the closest key is:
  - `(cycle_ts_utc, symbol, direction, source_system, signal_tier)`
  - but that key is not fully persisted because `signal_tier` only exists in script memory/spec, not the live execution-log schema

## 6. What can actually be normalized

### Safe core columns

These can be normalized across all three lanes without lying:
- `lane`
- `source_system`
- `source_kind`
  - example: `base_pass`, `scored_candidate`, `convergence_shortlist`, `daily_shortlist`, `risk_filtered`, `execution_pick`
- `ticker`
- `direction`
- `asof_date`
- `session_type`
  - example: `evening`, `night`, `daily`, `intraday_cycle`
- `run_date`
- `run_type`
  - nullable for lanes that do not use it
- `run_id`
  - nullable for lanes that do not use it
- `cycle_ts_utc`
  - nullable outside Vanguard
- `status`
  - but only at a generic level such as `PASS`, `BLOCK`, `PENDING`, `REJECTED`, `ACTIVE`, `FORWARD_TRACKED`
- `regime`
- `sector`
- `price`
- `rank`
- `created_at`
- `source_table`
- `source_artifact`
- `source_endpoint`

### Lane-specific columns

These should not be forced into the core schema:

S1-specific:
- `p_tp`
- `nn_p_tp`
- `scorer_prob`
- `convergence_score`
- `strategy_strength`
- `n_agree`
- `gate_source`
- `edge_score`
- `tradeable`
- `srs_multiplier`
- `options_multiplier`
- `sources`
- `earnings_risk`

Meridian-specific:
- `tcn_score`
- `factor_rank`
- `final_score`
- `predicted_return`
- `expected_return`
- `residual_alpha`
- `alpha`
- `conviction`
- `beta`
- `market_component`
- `top_shap_factors`

Vanguard-specific:
- `relative_volume`
- `spread_bps`
- `bars_available`
- `last_bar_ts_utc`
- all feature JSON contents such as:
  - `session_vwap_distance`
  - `premium_discount_zone`
  - `gap_pct`
  - `momentum_3bar`
  - `atr_expansion`
- execution-only fields:
  - `account_id`
  - `action`
  - `order_type`
  - `shares_or_lots`
  - `execution_bridge`
  - `bridge_order_id`

### Metadata JSON candidates

These should live in metadata JSON rather than the core schema:
- `scores_json`
  - S1: `p_tp`, `nn_p_tp`, `scorer_prob`, `convergence_score`
  - Meridian: `tcn_score`, `factor_rank`, `final_score`, `predicted_return`, `residual_alpha`, `beta`
  - Vanguard: health/feature values if candidate-like rows are ever materialized
- `source_metadata_json`
  - S1: `gate_source`, `strategies`, `sources`, `n_agree`, `tradeable`
  - Meridian: `top_shap_factors`, `market_component`
  - Vanguard: `signal_tier`, feature JSON, health breakdown
- `risk_metadata_json`
  - stops, targets, ATR, filter reasons, risk flags
- `report_metadata_json`
  - synthesis tags, brief reasons, dead-band reasons, earnings flags

## 7. Primary score analysis

### S1

Best candidate-level ranking score today:
- `scorer_prob`

Why:
- it is the persisted post-PASS ranking score
- it is used by `execute_daily_picks.py`
- it is the clearest candidate-level rank field in the real S1 pipeline today

Alternative S1 score:
- `convergence_score`

Why not primary by default:
- convergence is a shortlist/blend score from a separate artifact layer
- it is useful, but the current downstream tiering script starts from `scorer_predictions` and uses convergence as an enrichment

Most realistic S1 `primary_score`:
- `scorer_prob`

### Meridian

Best candidate-level ranking score today:
- `final_score`

Why:
- it is what `shortlist_daily` is ordered by in current live usage
- `execute_daily_picks.py` uses `final_score` as one of the key Meridian fields
- unlike `expected_return` and `alpha`, it is actually populated

Alternative Meridian score:
- `residual_alpha`

Why not primary today:
- semantically rich, but `final_score` is the actual live shortlist ordering field

Most realistic Meridian `primary_score`:
- `final_score`

### Vanguard

Best candidate-level ranking score today:
- none

Why:
- Vanguard has no native candidate shortlist table
- there is no persisted intraday selection score today
- `vanguard_health.status` is a health filter, not a candidate rank
- `vanguard_features.features_json` is raw model-input data, not candidate output

Closest thing today:
- external imported `signal_tier` in `execute_daily_picks.py`
- but this is not native Vanguard, and it is categorical rather than a pure ranking score

Most realistic Vanguard `primary_score` today:
- no honest answer exists yet

### Cross-lane comparability verdict

Is a single cross-lane comparable numeric `primary_score` realistic today?
- No.

Why:
- S1 `scorer_prob` is a post-PASS classifier probability
- Meridian `final_score` is a lane-specific ranking blend / score
- Vanguard has no native candidate score at all

Concrete verdict:
- a global cross-lane `primary_score` would be fake today
- the right move is:
  - keep `primary_score` lane-relative
  - store `primary_score_type`
  - keep raw lane scores in metadata JSON

## 8. Recommended normalization scope

### S1 + Meridian only?
- Yes, for MVP normalization this is the only honest scope.

Why:
- both lanes have real candidate tables/artifacts today
- both have live row-level candidate data with ticker, direction, rank-ish values, regime, and price
- both are already consumed downstream in live/report or execution-related code

### Vanguard later?
- Yes.

Why:
- Vanguard is not candidate-normalization ready today
- it is still a mix of:
  - prefilter health
  - feature blobs
  - external daily-pick execution ingestion
- there is no native shortlist table or risk-filtered candidate table

### Main blockers

S1 blockers:
- no durable schema-level unique candidate key in `scorer_predictions`
- `scorer_predictions` lacks `run_id` and `run_type`
- convergence richness lives partly in JSON and partly in DB mirror

Meridian blockers:
- `/api/candidates` is lossy relative to `shortlist_daily`
- newer Stage 5 fields (`expected_return`, `conviction`, `alpha`) exist in schema but are null in live rows
- table PK assumes one `(date, ticker)` candidate only

Vanguard blockers:
- `vanguard_selection.py` is zero bytes
- `vanguard_risk_filters.py` is zero bytes
- `vanguard_orchestrator.py` is zero bytes
- no live `vanguard_shortlist`
- no live `vanguard_tradeable_portfolio`
- no native intraday ranking score
- current `vanguard_execution_log` is execution history for imported daily picks, not native candidate generation

Bottom line:
- Normalize S1 + Meridian first.
- Treat Vanguard as out of MVP for candidate normalization.
- Revisit Vanguard only after it has a real native shortlist table and a persisted intraday ranking surface.
