# Meridian Codebase Reference

Generated from the live source tree on 2026-03-26. All 35 Python files py_compile successfully. No TODO/FIXME/HACK markers were found in Meridian Python source; the only TODO markers are in markdown specs, mainly the narrowed Playwright spec.

## Scope Read

- All Python files under the repo (35 total)
- Config JSON/Python under `config/` plus model config artifacts
- Repository markdown docs/specs outside `node_modules/`

## Database Tables in Live Meridian DB

`cache_meta`, `daily_bars`, `factor_history`, `factor_matrix_daily`, `options_daily`, `orchestrator_log`, `portfolio_state`, `predictions_daily`, `prefilter_results`, `shortlist_daily`, `trade_log`, `tradeable_portfolio`, `training_data`

## Python Files

### `colab_backfill_package.py`
**Purpose:** Builds a self-contained Colab package from Meridian OHLCV and factor code.
**CLI:** `python3 colab_backfill_package.py` with flags: --chunk-rows, --smoke-start, --smoke-end, --skip-smoke
**Dependencies:** No internal Meridian imports.
**Reads/Writes Tables:** daily_bars
**Key Functions:**
- `_progress(message) -> None`
- `_connect_db(db_path) -> sqlite3.Connection`
- `_package_root() -> Path`
- `_copy_support_files(package_dir) -> None`
- `_export_daily_bars_chunks(package_dir, chunk_rows=500000) -> list[Path]`
- `_colab_backfill_source() -> str`
- `_write_colab_script(package_dir) -> Path`
- `_build_zip(package_dir, zip_path) -> None`
- `_local_smoke_test(zip_path, start_date, end_date) -> None`
- `parse_args(argv=None) -> argparse.Namespace`
- `main(argv=None) -> int`
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Packages CSV chunks rather than SQLite because Colab handles CSV transport more reliably.
- The embedded colab_backfill.py now derives date range from OHLCV/SPY history, not existing training_data.
- Optional local smoke test is included to catch packaging/import errors before upload.

### `config/__init__.py`
**Purpose:** Package marker for config helpers.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** No internal Meridian imports.
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Input/Output Contract:** Package marker only. No runtime data contract beyond making imports work.

### `config/factor_registry.py`
**Purpose:** Loads the group-based factor registry and exposes active feature helpers.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** No internal Meridian imports.
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `load_registry(path=None)`
- `get_feature_groups(path=None)`
- `get_active_features(path=None, only_groups=None, exclude_groups=None)`
- `print_registry_status(path=None)`
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.

### `download_extended_data.py`
**Purpose:** Legacy root-level Alpaca downloader for extending daily_bars history.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** No internal Meridian imports.
**Reads/Writes Tables:** daily_bars
**Key Functions:**
- `alpaca_get(url, params=None)`
- `get_active_tickers()`
- `download_bars_for_ticker(ticker, start, end)`
- `main()`
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Legacy duplicate of stages/download_extended_data.py; both target the same daily_bars table.
- No argparse surface; edit constants or wrap externally if you need different ranges.

### `stages/__init__.py`
**Purpose:** Package marker for stage modules.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** No internal Meridian imports.
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Input/Output Contract:** Package marker only. No runtime data contract beyond making imports work.

### `stages/download_extended_data.py`
**Purpose:** Stage-local variant of the extended Alpaca history downloader.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** No internal Meridian imports.
**Reads/Writes Tables:** daily_bars
**Key Functions:**
- `alpaca_get(url, params=None)`
- `main()`
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Lean stage-local downloader with no argparse surface; still writes directly into daily_bars.
- Maintained alongside the root copy, so divergence between the two files is a risk.

### `stages/factors/__init__.py`
**Purpose:** Shared factor math, ET time helpers, and indicator primitives.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** No internal Meridian imports; this is the shared helper layer consumed by factor modules and stages.
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `now_et() -> datetime`
- `today_et() -> str`
- `today_et_date() -> date`
- `now_et_iso() -> str`
- `nan_dict(names) -> dict[str, float]`
- `z_score(series, window=20) -> float`
- `rolling_percentile(series, window=126) -> float`
- `wilder_smooth(values, period) -> list[float]`
- `compute_rsi(closes, period=14) -> pd.Series`
- `compute_atr(df, period=14) -> pd.Series`
- `compute_adx(df, period=14) -> dict[str, pd.Series]`
- `compute_macd_histogram(closes) -> pd.Series`
**Input/Output Contract:** Shared helper module. Consumed by factor modules and ET-sensitive stages for indicator math, z-scores, ATR/ADX/RSI, and Eastern Time date helpers.

### `stages/factors/m1_technical_core.py`
**Purpose:** Computes Module 1 technical-core stationary factors.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages/factors/__init__.py (relative imports)
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `_trend_persistence(closes) -> int`
- `compute_factors(df, spy_df, vix, sector, universe_stats) -> dict[str, float]`
**Input/Output Contract:** Pure factor module. Accepts `(df, spy_df, vix, sector, universe_stats)` and returns a `dict[str, float]` of stationary factors or NaNs when history is insufficient.

### `stages/factors/m2_structural_phase.py`
**Purpose:** Computes Wyckoff/phase-style structural factors.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages/factors/__init__.py (relative imports)
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `_phase_age(closes) -> int`
- `compute_factors(df, spy_df, vix, sector, universe_stats) -> dict[str, float]`
**Input/Output Contract:** Pure factor module. Accepts `(df, spy_df, vix, sector, universe_stats)` and returns a `dict[str, float]` of stationary factors or NaNs when history is insufficient.

### `stages/factors/m3_damage_shortside.py`
**Purpose:** Computes downside damage and short-side context factors.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages/factors/__init__.py (relative imports)
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `_count_true_from_end(series, cap) -> int`
- `compute_factors(df, spy_df, vix, sector, universe_stats) -> dict[str, float]`
**Input/Output Contract:** Pure factor module. Accepts `(df, spy_df, vix, sector, universe_stats)` and returns a `dict[str, float]` of stationary factors or NaNs when history is insufficient.

### `stages/factors/m4_mean_reversion.py`
**Purpose:** Computes mean-reversion setup factors.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages/factors/__init__.py (relative imports)
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `compute_factors(df, spy_df, vix, sector, universe_stats) -> dict[str, float]`
**Input/Output Contract:** Pure factor module. Accepts `(df, spy_df, vix, sector, universe_stats)` and returns a `dict[str, float]` of stationary factors or NaNs when history is insufficient.

### `stages/factors/m5_market_context.py`
**Purpose:** Computes relative-strength, options, breadth, and VIX context factors.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages/factors/__init__.py (relative imports)
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `_rs_vs_spy(close, spy_close, period) -> float`
- `compute_factors(df, spy_df, vix, sector, universe_stats) -> dict[str, float]`
**Input/Output Contract:** Pure factor module. Accepts `(df, spy_df, vix, sector, universe_stats)` and returns a `dict[str, float]` of stationary factors or NaNs when history is insufficient.

### `stages/tcn_scorer.py`
**Purpose:** Loads the passing TCN model and scores from factor_history sequences.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** No internal Meridian imports.
**Reads/Writes Tables:** factor_history
**Key Classes:**
- `CausalConv1d` — `__init__(in_ch, out_ch, kernel, dilation=1)`, `forward(x) -> torch.Tensor`
- `TCNClassifier` — `__init__(n_features)`, `forward(x) -> torch.Tensor`
- `TCNScorer` — `__init__(model_dir=None, db_path=None)`, `_load_factor_history(target_date) -> pd.DataFrame`, `_rank_normalize(frame) -> pd.DataFrame`, `score(target_date) -> pd.DataFrame`
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Requires factor_history to have at least 64 dates and model files under models/tcn_pass_v1/.
- Applies cross-sectional rank normalization per date before sequence assembly to match training-time distribution.
- Raises FileNotFoundError when model files are absent; Stage 5 handles the neutral-score fallback.

### `stages/v2_api_server.py`
**Purpose:** FastAPI read/API surface over Meridian DB state and risk sizing.
**CLI:** `python3 stages/v2_api_server.py` with flags: --port, --host, --db
**Dependencies:** stages.factors, stages.v2_risk_filters
**Reads/Writes Tables:** cache_meta, daily_bars, factor_matrix_daily, orchestrator_log, portfolio_state, prefilter_results, shortlist_daily, trade_log, tradeable_portfolio, training_data
**Key Functions:**
- `_progress(message) -> None`
- `_connect_db(db_path=DEFAULT_DB_PATH) -> sqlite3.Connection`
- `_table_exists(con, name) -> bool`
- `_latest_date(con, table) -> str | None`
- `_get_meta(con, key) -> str | None`
- `_safe_rows(con, sql, params=()) -> list[dict[str, Any]]`
- `_safe_one(con, sql, params=()) -> dict[str, Any] | None`
- `_default_portfolio_state() -> dict[str, Any]`
- `_normalize_candidate_rows(rows) -> list[dict[str, Any]]`
- `_load_settings() -> dict[str, Any]`
- `_load_latest_price_and_atr(con, ticker) -> tuple[float | None, float | None]`
- `create_app(db_path=DEFAULT_DB_PATH) -> FastAPI`
**Key Classes:**
- `SizeRequest` — no public methods
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Returns safe defaults or empty lists when tables are missing instead of raising 500s.
- Uses yfinance on /api/v2/ticker/{ticker}; network failures return a shaped error payload rather than crashing.
- Current UI contract is API-first; there is no HTML dashboard served directly by this Python server.

### `stages/v2_cache_warm.py`
**Purpose:** Stage 1 cache pipeline for daily bars, options, validation, and run report.
**CLI:** `python3 stages/v2_cache_warm.py` with flags: --dry-run, --skip-alpaca, --skip-yf, --skip-options, --days, --full-refresh, --db
**Dependencies:** stages.factors
**Reads/Writes Tables:** cache_meta, daily_bars, options_daily
**Key Functions:**
- `_generated_at_utc() -> str`
- `_run_now_iso() -> str`
- `_resolve_db_path(db_arg=None) -> Path`
- `_guard_db_path(db_path) -> None`
- `_connect_db(db_path) -> sqlite3.Connection`
- `_ensure_v2_db(db_path) -> None`
- `_set_meta(con, key, value) -> None`
- `_write_daily_rows(con, rows) -> int`
- `_write_options_rows(con, rows) -> int`
- `_get_last_trading_day(ref=None) -> date`
- `_retry_json_request(url, headers=None, timeout=30, retries=3) -> Any`
- `_load_sector_map() -> dict[str, str]`
**Key Classes:**
- `CacheWarmError` — no public methods
- `ValidationAbort` — no public methods
- `StepResult` — no public methods
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Uses Alpaca IEX feed rather than SIP; alignment is a warning above 50% and a hard fail only below that threshold.
- Price-jump validation is warning-only unless flagged names exceed the hard corruption threshold.
- Dry-run skips credential enforcement and prints the plan without DB writes.

### `stages/v2_factor_engine.py`
**Purpose:** Stage 3 shell that computes active factors and writes factor_matrix_daily.
**CLI:** `python3 stages/v2_factor_engine.py` with flags: --db, --workers, --dry-run, --debug, --prefilter-cache, --no-prefilter-cache, --skip-prefilter
**Dependencies:** config.factor_registry, stages.factors, stages.v2_prefilter
**Reads/Writes Tables:** cache_meta, daily_bars, factor_matrix_daily, options_daily, prefilter_results
**Key Functions:**
- `_progress(message) -> None`
- `_connect_db(db_path) -> sqlite3.Connection`
- `_load_registry() -> dict[str, Any]`
- `_active_registry_entries(registry) -> list[dict[str, Any]]`
- `_load_sector_map() -> dict[str, str]`
- `_table_exists(con, name) -> bool`
- `_get_meta(con, key) -> str | None`
- `_load_ohlcv_map(db_path, tickers) -> dict[str, pd.DataFrame]`
- `_load_options_map(db_path, tickers) -> dict[str, dict[str, float]]`
- `_pick_vix_history(ohlcv_map) -> tuple[pd.Series, float]`
- `compute_universe_stats(all_ohlcv, spy_df, vix_history, sector_map, options_map) -> dict[str, Any]`
- `_validate_registry(registry) -> tuple[list[str], dict[str, list[str]]]`
**Key Classes:**
- `FactorEngineError` — no public methods
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Active factors come from config/factor_registry.py and the JSON group schema, not a flat registry list.
- Can reuse same-day prefilter_results instead of rerunning Stage 2.
- Writes factor_matrix_daily and relies on the orchestrator to persist factor_history snapshots.

### `stages/v2_fundamental_enrichment.py`
**Purpose:** Adds fundamental/calendar columns to training_data and exports the NN sandbox CSV.
**CLI:** `python3 stages/v2_fundamental_enrichment.py` with flags: --dry-run, --fetch-only
**Dependencies:** No internal Meridian imports.
**Reads/Writes Tables:** training_data
**Key Functions:**
- `fetch_fundamentals(tickers) -> dict[str, dict]`
- `_safe_log10(v) -> float | None`
- `_clip(v, lo, hi) -> float | None`
- `build_fundamental_row(cache_entry) -> dict`
- `build_calendar_row(date_str, sector) -> dict`
- `_median(values) -> float | None`
- `fill_cross_sectional_medians(rows, fund_cols) -> list[dict]`
- `ensure_new_columns(con) -> None`
- `run(dry_run=False, fetch_only=False) -> dict`
- `main() -> int`
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Writes directly into training_data and exports a CSV into ~/SS/NN_Sandbox, so it is the one Meridian script with an intentional external path dependency.
- Fetch-only mode only refreshes the JSON cache; dry-run enriches in memory without DB writes.

### `stages/v2_orchestrator.py`
**Purpose:** Stage 7 orchestrator chaining stages 1-6 with logging and fallback behavior.
**CLI:** `python3 stages/v2_orchestrator.py` with flags: --db, --stage, --skip-cache, --full-refresh, --mock-ml, --no-mock-ml, --dry-run, --no-telegram, --prop-firm, --debug, --days
**Dependencies:** stages.factors, stages.tcn_scorer, stages.v2_cache_warm, stages.v2_factor_engine, stages.v2_prefilter, stages.v2_risk_filters, stages.v2_selection
**Reads/Writes Tables:** cache_meta, factor_history, orchestrator_log, predictions_daily, prefilter_results
**Key Functions:**
- `_progress(message) -> None`
- `_connect_db(db_path) -> sqlite3.Connection`
- `_ensure_meta_tables(con) -> None`
- `_set_meta(con, key, value) -> None`
- `_write_orchestrator_log(db_path, outcomes) -> None`
- `_load_latest_prefilter(db_path) -> pd.DataFrame`
- `_write_mock_predictions(db_path, frame) -> int`
- `_write_factor_history(db_path, frame) -> int`
- `_send_telegram_summary(message, no_telegram) -> str`
- `_format_summary(outcomes) -> str`
- `_log_debug_prefilter(frame, ticker) -> None`
- `_log_debug_factors(frame, ticker) -> None`
**Key Classes:**
- `OrchestratorError` — no public methods
- `StageOutcome` — no public methods
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Stages 1-3 are hard dependencies; stages 4-6 warn/degrade instead of aborting the whole run.
- Mock ML defaults on; predictions_daily is seeded when no trained Stage 4B model is being used.
- Also owns factor_history table creation and daily snapshot persistence.

### `stages/v2_prefilter.py`
**Purpose:** Stage 2 SQL-first universe prefilter and regime tagging pass.
**CLI:** `python3 stages/v2_prefilter.py` with flags: --db, --min-price, --min-dollar-volume, --min-bars, --dry-run
**Dependencies:** stages.factors
**Reads/Writes Tables:** cache_meta, daily_bars, prefilter_results
**Key Functions:**
- `_generated_at_utc() -> str`
- `_run_now_iso() -> str`
- `_resolve_db_path(db_arg=None) -> Path`
- `_guard_db_path(db_path) -> None`
- `_connect_db(db_path) -> sqlite3.Connection`
- `_load_sector_map() -> dict[str, str]`
- `_table_exists(con, name) -> bool`
- `_get_cache_meta(con, key) -> str | None`
- `_require_stage1_ready(con) -> str`
- `_suffix_excluded(ticker) -> bool`
- `_leveraged_or_inverse_excluded(ticker) -> bool`
- `_ticker_excluded(ticker) -> bool`
**Key Classes:**
- `PrefilterError` — no public methods
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Requires cache_meta.validation_status=PASS before doing any work.
- SPY is force-kept through filters even if it would otherwise fail thresholds.
- Writes cached survivors into prefilter_results for Stage 3 hot-path reuse.

### `stages/v2_risk_filters.py`
**Purpose:** Stage 6 position sizing and portfolio/risk gating engine.
**CLI:** `python3 stages/v2_risk_filters.py` with flags: --db, --account-balance, --risk-per-trade, --max-positions, --dry-run, --prop-firm, --debug, --mock, --tickers, --directions, --size
**Dependencies:** stages.factors, stages.v2_selection
**Reads/Writes Tables:** cache_meta, daily_bars, portfolio_state, prefilter_results, shortlist_daily, trade_log, tradeable_portfolio
**Key Functions:**
- `_progress(message) -> None`
- `_connect_db(db_path) -> sqlite3.Connection`
- `_table_exists(con, name) -> bool`
- `_latest_table_date(con, table) -> str | None`
- `_csv_upper(value) -> list[str]`
- `load_risk_config(prop_firm='ftmo', account_balance=None, risk_per_trade=None, max_positions=None) -> dict[str, Any]`
- `_ensure_risk_tables(con) -> None`
- `_load_portfolio_state(con, config) -> dict[str, Any]`
- `_best_day_metrics(con) -> tuple[float, float, int]`
- `_load_shortlist(db_path, mock, show_all=False) -> pd.DataFrame`
- `_load_prefilter_lookup(con) -> pd.DataFrame`
- `_load_price_history(db_path, tickers, bars=120) -> dict[str, pd.DataFrame]`
**Key Classes:**
- `RiskFilterError` — no public methods
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Without --tickers it evaluates all shortlist candidates and records APPROVED/REJECTED status rather than auto-selecting a subset.
- Can run in mock mode before live ML exists.
- Writes tradeable_portfolio and portfolio_state even in the factor-only fallback path.

### `stages/v2_selection.py`
**Purpose:** Stage 5 ranking and shortlist generation with optional TCN blending.
**CLI:** `python3 stages/v2_selection.py` with flags: --db, --top-n, --min-residual, --show-all, --dry-run, --debug, --mock
**Dependencies:** stages.factors, stages.tcn_scorer, stages.v2_prefilter
**Reads/Writes Tables:** cache_meta, daily_bars, predictions_daily, prefilter_results, shortlist_daily
**Key Functions:**
- `_progress(message) -> None`
- `_connect_db(db_path) -> sqlite3.Connection`
- `_get_tcn_scorer() -> TCNScorer | None`
- `_table_exists(con, name) -> bool`
- `_load_prefilter_frame(db_path) -> pd.DataFrame`
- `generate_mock_predictions(prefilter_df) -> pd.DataFrame`
- `_load_predictions_frame(db_path, mock) -> pd.DataFrame`
- `_load_return_map(db_path, tickers) -> dict[str, pd.Series]`
- `compute_beta(ticker_returns, spy_returns, window=BETA_WINDOW) -> float`
- `clamp_beta(beta, limit=BETA_CLAMP) -> float`
- `_extract_top_shap_factors(row) -> tuple[str | None, list[str]]`
- `_ensure_shortlist_table(con) -> None`
**Key Classes:**
- `SelectionError` — no public methods
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Falls back to neutral tcn_score=0.5 when the TCN model is missing.
- Uses side-aware factor percentiles so shorts are not disadvantaged by a global long-biased rank.
- Writes shortlist_daily and clears same-day rows before insert-or-replace to avoid stale shortlist contamination.

### `stages/v2_training_backfill.py`
**Purpose:** Stage 4A historical factor backfill and forward-return label generator.
**CLI:** `python3 stages/v2_training_backfill.py` with flags: --db, --start-date, --end-date, --tickers, --sample, --workers, --batch-days, --dry-run, --debug
**Dependencies:** stages, stages.factors
**Reads/Writes Tables:** daily_bars, training_data
**Key Functions:**
- `_progress(message) -> None`
- `_generated_at_utc() -> str`
- `_connect_db(db_path) -> sqlite3.Connection`
- `_load_registry() -> dict[str, Any]`
- `_active_factor_names() -> list[str]`
- `_active_by_module() -> dict[str, list[str]]`
- `_load_all_ohlcv(db_path) -> dict[str, pd.DataFrame]`
- `_date_arrays(all_ohlcv) -> dict[str, list[str]]`
- `_slice_up_to_date(df, current_date) -> pd.DataFrame`
- `compute_forward_return(all_ohlcv, ticker, current_date, horizon=FORWARD_HORIZON) -> float`
- `_historical_prefilter(all_ohlcv, current_date, allowed_tickers, sector_map, min_price=MIN_PRICE, min_dollar_volume=MIN_DOLLAR_VOLUME, min_bars=MIN_BARS) -> tuple[list[str], dict[str, dict[str, Any]]]`
- `_module_nan_dict(module_name, active_by_module) -> dict[str, float]`
**Key Classes:**
- `TrainingBackfillError` — no public methods
**Input/Output Contract:** See function/class signatures above; this file is part of the production or support pipeline and is invoked either directly from CLI or imported by another stage.
**Known Quirks / Gotchas:**
- Loads all OHLCV into memory once; runtime is dominated by date iteration, not DB round-trips.
- Forward returns are 5 trading bars, not calendar days.
- Debug mode prints per-date factor dumps and can be paired with --dry-run to avoid writes.

### `tests/__init__.py`
**Purpose:** Package marker for Meridian pytest modules.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** No internal Meridian imports.
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Input/Output Contract:** Package marker only. No runtime data contract beyond making imports work.

### `tests/test_m1_technical_core.py`
**Purpose:** Unit tests for Module 1 factor outputs and bounds.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages.factors
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `_bars(n=260, start=50.0, drift=0.2, volume=100000.0) -> pd.DataFrame`
- `test_m1_returns_all_18_factors() -> None`
- `test_m1_bounded_outputs() -> None`
- `test_m1_short_history_returns_nan_dict() -> None`
- `test_m1_zero_volume_and_constant_price_do_not_crash() -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_m2_structural_phase.py`
**Purpose:** Unit tests for Module 2 structural-phase outputs.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages.factors
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `_bars(n=120, start=20.0) -> pd.DataFrame`
- `test_m2_returns_5_factors() -> None`
- `test_m2_bounds() -> None`
- `test_m2_short_history_returns_nan() -> None`
- `test_m2_constant_price_returns_unknown_phase_zero() -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_m3_damage_shortside.py`
**Purpose:** Unit tests for Module 3 damage/short-side outputs.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages.factors
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `_bars(n=260, falling=False) -> pd.DataFrame`
- `test_m3_returns_6_factors() -> None`
- `test_m3_damage_depth_signs() -> None`
- `test_m3_short_history_returns_nan() -> None`
- `test_m3_ma200_factor_nan_when_history_under_200() -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_m4_mean_reversion.py`
**Purpose:** Unit tests for Module 4 mean-reversion outputs.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages.factors
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `_bars(n=260, oversold=False) -> pd.DataFrame`
- `test_m4_returns_4_factors() -> None`
- `test_m4_scores_bounded() -> None`
- `test_m4_short_history_returns_nan() -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_m5_market_context.py`
**Purpose:** Unit tests for Module 5 market-context outputs.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages.factors
**Reads/Writes Tables:** No direct Meridian DB table access detected.
**Key Functions:**
- `_bars(n=120, ticker='AAPL') -> pd.DataFrame`
- `test_m5_returns_14_factors() -> None`
- `test_m5_rs_math_and_bounds() -> None`
- `test_m5_unmapped_sector_and_missing_options() -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_v2_cache.py`
**Purpose:** Stage 1 tests for schema, validation gate, and dry-run behavior.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages
**Reads/Writes Tables:** cache_meta, daily_bars, options_daily
**Key Functions:**
- `_use_tmp_meridian(tmp_path, monkeypatch) -> None`
- `_table_names(db_path) -> list[str]`
- `_insert_daily_rows(db_path, rows) -> None`
- `test_ensure_v2_db_creates_required_tables(tmp_path, monkeypatch) -> None`
- `test_guard_db_path_rejects_s1_and_s8_paths() -> None`
- `test_write_daily_rows_is_idempotent(tmp_path, monkeypatch) -> None`
- `test_load_yf_diff_tickers_subtracts_alpaca_set(tmp_path, monkeypatch) -> None`
- `test_load_sector_map_reads_meridian_json(tmp_path, monkeypatch) -> None`
- `test_run_pipeline_dry_run_does_not_require_alpaca_credentials(tmp_path, monkeypatch) -> None`
- `test_validation_gate_aborts_if_spy_missing(tmp_path, monkeypatch) -> None`
- `test_validation_gate_aborts_if_spy_stale(tmp_path, monkeypatch) -> None`
- `test_validation_gate_aborts_on_excess_price_jumps(tmp_path, monkeypatch) -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_v2_factor_engine.py`
**Purpose:** Stage 3 integration tests for writes, debug mode, and prefilter cache reuse.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages
**Reads/Writes Tables:** cache_meta, daily_bars, factor_matrix_daily, options_daily, prefilter_results
**Key Functions:**
- `_seed_db(db_path) -> None`
- `test_factor_engine_dry_run_and_write(tmp_path, monkeypatch) -> None`
- `test_factor_engine_debug_mode(tmp_path, monkeypatch) -> None`
- `test_factor_engine_uses_cached_prefilter_results(tmp_path, monkeypatch) -> None`
- `test_factor_engine_skip_prefilter_requires_cache(tmp_path, monkeypatch) -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_v2_orchestrator.py`
**Purpose:** Stage 7 tests for ordering, abort/degrade logic, and log writes.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages, stages.v2_prefilter, stages.v2_selection
**Reads/Writes Tables:** cache_meta, orchestrator_log
**Key Functions:**
- `_prefilter_df() -> pd.DataFrame`
- `_factor_df() -> pd.DataFrame`
- `_prediction_df() -> pd.DataFrame`
- `_shortlist_df() -> pd.DataFrame`
- `_risk_df() -> pd.DataFrame`
- `_risk_state() -> dict[str, float]`
- `test_orchestrator_runs_stages_in_order(tmp_path, monkeypatch) -> None`
- `test_orchestrator_aborts_on_stage2_failure(tmp_path, monkeypatch) -> None`
- `test_orchestrator_degrades_on_stage5_failure(tmp_path, monkeypatch) -> None`
- `test_orchestrator_stage_specific_run(tmp_path, monkeypatch) -> None`
- `test_orchestrator_writes_log_table(tmp_path, monkeypatch) -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_v2_prefilter.py`
**Purpose:** Stage 2 tests for filters, SPY survival, persistence, and exclusions.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages
**Reads/Writes Tables:** cache_meta, daily_bars, prefilter_results
**Key Functions:**
- `_use_tmp_meridian(tmp_path, monkeypatch) -> None`
- `_seed_db(db_path, validation='PASS') -> None`
- `_insert_ticker(db_path, ticker, bars=60, start_price=10.0, price_step=0.2, volume=100000.0) -> None`
- `_write_sector_map(tmp_path, monkeypatch) -> Path`
- `test_tickers_below_floor_price_are_removed(tmp_path, monkeypatch) -> None`
- `test_tickers_below_dollar_volume_floor_are_removed(tmp_path, monkeypatch) -> None`
- `test_suffix_exclusions_remove_special_security_types(tmp_path, monkeypatch) -> None`
- `test_tickers_with_less_than_min_bars_are_removed(tmp_path, monkeypatch) -> None`
- `test_spy_always_survives_all_filters(tmp_path, monkeypatch) -> None`
- `test_every_survivor_has_valid_regime_tag(tmp_path, monkeypatch) -> None`
- `test_no_negative_prices_in_output(tmp_path, monkeypatch) -> None`
- `test_aborts_if_db_missing(tmp_path, monkeypatch) -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_v2_risk_filters.py`
**Purpose:** Stage 6 tests for config loading, math, sector caps, and writes.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages
**Reads/Writes Tables:** cache_meta, daily_bars, portfolio_state, prefilter_results, trade_log, tradeable_portfolio
**Key Functions:**
- `_seed_db(db_path) -> None`
- `test_load_risk_config_preset_override() -> None`
- `test_compute_position_math() -> None`
- `test_check_correlation_blocks_highly_correlated_series() -> None`
- `test_risk_filters_sector_cap(tmp_path, monkeypatch) -> None`
- `test_risk_filters_writes_tables(tmp_path, monkeypatch) -> None`
- `test_manual_ticker_mode_uses_requested_direction(tmp_path) -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_v2_selection.py`
**Purpose:** Stage 5 tests for ranking, writes, beta clamp, and show-all behavior.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages
**Reads/Writes Tables:** cache_meta, daily_bars, prefilter_results, shortlist_daily
**Key Functions:**
- `_seed_db(db_path) -> None`
- `test_generate_mock_predictions_is_deterministic() -> None`
- `test_compute_beta_known_relation() -> None`
- `test_selection_ranks_by_residual_not_raw_prediction(tmp_path, monkeypatch) -> None`
- `test_selection_writes_shortlist_daily(tmp_path) -> None`
- `test_selection_replaces_prior_rows_for_same_date(tmp_path) -> None`
- `test_selection_show_all_returns_ranked_universe_without_threshold(tmp_path, monkeypatch) -> None`
- `test_selection_clamps_extreme_betas(tmp_path, monkeypatch) -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

### `tests/test_v2_training_backfill.py`
**Purpose:** Stage 4A tests for no-lookahead, label math, idempotence, and debug output.
**CLI:** No argparse CLI surface; import this module or execute it directly only where the file defines an `if __name__ == "__main__"` block.
**Dependencies:** stages
**Reads/Writes Tables:** daily_bars, training_data
**Key Functions:**
- `_seed_db(db_path) -> None`
- `_sector_map(tmp_path) -> Path`
- `test_forward_return_computation_is_correct(tmp_path, monkeypatch) -> None`
- `test_forward_return_nan_when_insufficient_future_bars(tmp_path) -> None`
- `test_slice_up_to_date_has_no_lookahead(tmp_path) -> None`
- `test_historical_prefilter_removes_sub_dollar_ticker(tmp_path, monkeypatch) -> None`
- `test_training_rows_have_active_factor_columns_and_target(tmp_path, monkeypatch) -> None`
- `test_insert_or_replace_is_idempotent(tmp_path, monkeypatch) -> None`
- `test_sample_limits_ticker_count(tmp_path, monkeypatch) -> None`
- `test_dry_run_does_not_write_db(tmp_path, monkeypatch) -> None`
- `test_debug_prints_factor_dump(tmp_path, monkeypatch, capsys) -> None`
**Input/Output Contract:** Pytest module; seeds temp DB/data, exercises a narrow contract, and asserts behavior without writing production artifacts.

## Config and Model Artifacts

### `config/factor_registry.json`
- Group-based feature registry. Source of truth for enabled factor groups and feature names. Read by config/factor_registry.py and Stage 3/4A.
- Top-level keys: _meta, groups

### `config/risk_config.json`
- Risk defaults and preset overrides (for example FTMO). Read by Stage 6 and surfaced through the API settings endpoint.
- Top-level keys: defaults, presets

### `config/ticker_sector_map.json`
- Meridian-local sector lookup map used by Stage 2 and historical/backfill flows.
- Top-level keys: A, AA, AAL, AAP, AAPL, ABBV, ABC, ABNB, ABT, ACAD, ACLS, ADBE, AEHR, AEIS, AEO, AEP, AES, AFL, AFRM, AGCO

### `models/feature_list.json`
- Flat feature list artifact for model/training workflows. Stored model-side rather than under config/.
- List length: 32

### `models/meridian_tcn_pass_config.json`
- Reference TCN metadata/config artifact for the passing Meridian model.
- Top-level keys: architecture, data, features, hit_rate, ic, label_thresholds, labeling, lookback, model, n_features, spread, timestamp, training, verdict, walk_forward

### `models/tcn_pass_v1/config.json`
- Live config paired with the deployed local TCN scoring model.
- Top-level keys: architecture, data, features, hit_rate, ic, label_thresholds, labeling, lookback, model, n_features, spread, timestamp, training, verdict, walk_forward

### `models/tcn_pass_v1/model.pt`
- Binary PyTorch weights file for the local TCN scorer; not human-readable and not py_compile-able.

## Markdown / Spec Map

Only repository-authored markdown is listed here; vendored `node_modules` docs are intentionally excluded.

- `AGENTS.md` — Meridian — Quantitative Trading Factor Model
- `CC_FIX_3_BLOCKERS.md` — CC Fix 1 of 3: Build API Server (Q3 Blocker)
- `CHEATSHEET.md` — Meridian v2 — Quick Reference Cheat Sheet
- `CODEX_STAGE4B_PROMPT.md` — Codex Task: Build Meridian Stage 4B — ML Model Trainer
- `README.md` — Meridian
- `ROADMAP.md` — Meridian — Build Roadmap
- `audit_report_15_blindspots.md` — Meridian — 15-Point Blind Spot Audit Report
- `ba_spec_colab_backfill.md` — BA Spec: Create Self-Contained Backfill Package for Google Colab
- `ba_spec_full_qa.md` — BA Spec: Full QA + UAT Pass — Meridian Stages 1-7
- `ba_spec_fundamental_data.md` — BA Spec: Add Fundamental Data to Meridian Training Data
- `ba_spec_meridian_tcn.md` — BA Spec: Adapt NN_Sandbox for Meridian v2 Features
- `ba_spec_playwright_tests.md` — BA Spec: Playwright UI/UAT Tests — Meridian Dashboard (Narrowed to Live API)
- `ba_spec_react_wiring.md` — BA Spec: Wire React App to Meridian API Server + End-to-End Testing
- `ba_spec_tcn_wire.md` — BA Spec: Wire Passing TCN Model into Stage 5 Selection
- `ba_spec_tcn_wire_v2.md` — BA Spec: Wire Passing TCN Model into Meridian Pipeline (UPDATED)
- `ba_spec_ui_tradingview.md` — BA Spec: TradingView Chart Integration + Ticker Info
- `ba_spec_vercel_deploy.md` — BA Spec: Deploy Meridian Dashboard to Vercel
- `docs/CODEX_STAGE1_PROMPT.md` — Codex Task: Build Meridian Stage 1 — Cache Pipeline
- `docs/CODEX_STAGE2_PROMPT.md` — Codex Task: Build Meridian Stage 2 — Prefilter
- `docs/CODEX_STAGE3_PROMPT.md` — Codex Task: Build Meridian Stage 3 — Factor Engine (5 modules, 34 factors)
- `docs/CODEX_STAGE4A_PROMPT.md` — Codex Task: Build Meridian Stage 4A — Training Data Backfill
- `docs/CODEX_STAGE5_6_PROMPT.md` — Codex Task: Build Meridian Stages 5 + 6 — Selection + Risk Filters
- `docs/CODEX_STAGE7_PROMPT.md` — Codex Task: Build Meridian Stage 7 — Orchestrator
- `docs/KNOWN_ISSUES.md` — Known Issues — Mistakes from S1 to NOT Repeat in Meridian
- `docs/OPERATIONAL_STANDARDS.md` — Meridian — Operational Standards for All Scripts
- `docs/S1_REFERENCE.md` — S1 Reference — Code to Copy and Code to Avoid
- `docs/STAGE_1_CACHE_SPEC.md` — STAGE 1: Cache Pipeline — v2_cache_warm.py
- `docs/STAGE_2_PREFILTER_SPEC.md` — STAGE 2: Prefilter — v2_prefilter.py
- `docs/STAGE_3A_TECHNICAL_CORE_SPEC.md` — STAGE 3A: Module 1 — Technical Core (18 factors)
- `docs/STAGE_3B_STRUCTURAL_DAMAGE_SPEC.md` — STAGE 3B: Modules 2 + 3 — Structural Phase + Damage/Short-Side (11 factors)
- `docs/STAGE_3C_REVERSION_CONTEXT_SPEC.md` — STAGE 3C: Modules 4 + 5 — Mean Reversion + Market Context (18 factors)
- `docs/STAGE_3_ENGINE_SPEC.md` — STAGE 3: Factor Engine — v2_factor_engine.py (Shell + Architecture)
- `docs/STAGE_4A_TRAINING_BACKFILL_SPEC.md` — STAGE 4A: Training Data Backfill — v2_training_backfill.py
- `docs/STAGE_4B_MODEL_TRAINER_SPEC.md` — STAGE 4B: ML Model Training — v2_model_trainer.py
- `docs/STAGE_5_SELECTION_SPEC.md` — STAGE 5: Selection — v2_selection.py
- `docs/STAGE_6_RISK_FILTERS_SPEC.md` — STAGE 6: Risk Filters — v2_risk_filters.py
- `docs/STAGE_7_ORCHESTRATOR_SPEC.md` — STAGE 7: Orchestrator — v2_orchestrator.py
- `docs/cli_reference.md` — Meridian CLI Reference
- `docs/codebase_reference.md` — Meridian Codebase Reference
- `docs/debug_commands.md` — Meridian Debug Commands
- `docs/final_review_signoff.md` — Meridian Final Review Sign-Off
- `docs/meridian_architecture_system_doc.md` — SignalStack Meridian v2 — Architecture & System Document
- `docs/qa_report_stage2_prefilter.md` — Meridian Stage 2 QA Report
- `docs/qa_report_stage3.md` — Meridian Stage 3 QA Report
- `docs/qa_report_stage4a.md` — Meridian Stage 4A QA Report
- `docs/qa_report_stage5_6.md` — Meridian Stage 5 + 6 QA Report
- `docs/qa_report_stage7.md` — Meridian Stage 7 QA Report
- `meridian_next_steps.md` — Meridian v2 — Next Steps: Backfill → Training → Model Integration
- `prompt_codex_codebase_docs.md` — Codex Prompt: Codebase Documentation + Debug Commands + CLI Reference
- `prompt_final_signoff.md` — Final Review & Sign-Off — Meridian v2 End-to-End
- `qa_report_full_pipeline.md` — Meridian Full Pipeline QA + UAT
- `ui/signalstack-app/.next/standalone/node_modules/@img/sharp-libvips-darwin-arm64/README.md` — `@img/sharp-libvips-darwin-arm64`
- `ui/signalstack-app/AGENTS.md` — This is NOT the Next.js you know
- `ui/signalstack-app/CLAUDE.md` — (no heading)
- `ui/signalstack-app/README.md` — Getting Started
- `ui/signalstack-app/integration_test_report.md` — Meridian React ↔ API Integration Test Report
- `ui/stitch/quant_edge/DESIGN.md` — Design System Document: Quantitative Precision

## TODO/FIXME/HACK Scan

- Python source: none found.
- Markdown TODOs: present in `ba_spec_playwright_tests.md` for blocked future UI/API tests.
