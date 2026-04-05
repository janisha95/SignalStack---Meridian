# Meridian CLI Reference
All commands assume `cd /Users/sjani008/SS/Meridian` unless noted.
## Primary Pipeline Entry Points
| Script | Command | Purpose |
|---|---|---|
| stages/v2_orchestrator.py | `python3 stages/v2_orchestrator.py [--stage N|all] [--skip-cache] [--mock-ml/--no-mock-ml] [--dry-run] [--no-telegram] [--prop-firm ftmo] [--debug TICKER] [--days 5] [--db PATH]` | Run the full stage chain or isolate one stage. |
| stages/v2_cache_warm.py | `python3 stages/v2_cache_warm.py [--dry-run] [--skip-alpaca] [--skip-yf] [--skip-options] [--days 5] [--full-refresh] [--db PATH]` | Stage 1 cache warm and validation gate. |
| stages/v2_prefilter.py | `python3 stages/v2_prefilter.py [--db PATH] [--min-price 2] [--min-dollar-volume 1000000] [--min-bars 50] [--dry-run]` | Stage 2 SQL-first prefilter. |
| stages/v2_factor_engine.py | `python3 stages/v2_factor_engine.py [--db PATH] [--workers 8] [--dry-run] [--debug TICKER] [--prefilter-cache|--no-prefilter-cache] [--skip-prefilter]` | Stage 3 factor computation and matrix write. |
| stages/v2_training_backfill.py | `python3 stages/v2_training_backfill.py [--db PATH] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--tickers CSV] [--sample N] [--workers N] [--batch-days N] [--dry-run] [--debug TICKER]` | Stage 4A historical training_data backfill. |
| stages/tcn_scorer.py | `python3 stages/tcn_scorer.py` | Smoke-test model/config loading for Stage 4B inference. |
| stages/v2_selection.py | `python3 stages/v2_selection.py [--db PATH] [--top-n 30] [--min-residual 0.0] [--show-all] [--dry-run] [--debug TICKER] [--mock]` | Stage 5 ranking and shortlist generation. |
| stages/v2_risk_filters.py | `python3 stages/v2_risk_filters.py [--db PATH] [--account-balance X] [--risk-per-trade X] [--max-positions N] [--dry-run] [--prop-firm ftmo] [--debug TICKER] [--mock] [--tickers CSV --directions CSV] [--size TICKER DIRECTION]` | Stage 6 risk evaluation and sizing. |
| stages/v2_api_server.py | `python3 stages/v2_api_server.py [--host 0.0.0.0] [--port 8080] [--db PATH]` | Run the FastAPI server used by the UI. |

## Support / Utility Scripts
| Script | Command | Purpose |
|---|---|---|
| colab_backfill_package.py | `python3 colab_backfill_package.py [--chunk-rows 500000] [--smoke-start YYYY-MM-DD] [--smoke-end YYYY-MM-DD] [--skip-smoke]` | Export daily_bars and package a self-contained Colab backfill zip. |
| stages/v2_fundamental_enrichment.py | `python3 stages/v2_fundamental_enrichment.py [--dry-run] [--fetch-only]` | Fetch/cache fundamentals and enrich `training_data`. |
| download_extended_data.py | `python3 download_extended_data.py` | Legacy root-level extended Alpaca downloader. |
| stages/download_extended_data.py | `python3 stages/download_extended_data.py` | Stage-local duplicate extended downloader. |
| config/factor_registry.py | `python3 config/factor_registry.py` | Print enabled/disabled factor-group status from the registry. |

## Non-CLI Python Modules
These files are import-oriented modules rather than standalone CLIs:
- `config/__init__.py` — Package marker for config helpers.
- `stages/__init__.py` — Package marker for stage modules.
- `stages/factors/__init__.py` — Shared factor math, ET time helpers, and indicator primitives.
- `stages/factors/m1_technical_core.py` — Computes Module 1 technical-core stationary factors.
- `stages/factors/m2_structural_phase.py` — Computes Wyckoff/phase-style structural factors.
- `stages/factors/m3_damage_shortside.py` — Computes downside damage and short-side context factors.
- `stages/factors/m4_mean_reversion.py` — Computes mean-reversion setup factors.
- `stages/factors/m5_market_context.py` — Computes relative-strength, options, breadth, and VIX context factors.
- `tests/__init__.py` — Package marker for Meridian pytest modules.
- `tests/test_m1_technical_core.py` — Unit tests for Module 1 factor outputs and bounds.
- `tests/test_m2_structural_phase.py` — Unit tests for Module 2 structural-phase outputs.
- `tests/test_m3_damage_shortside.py` — Unit tests for Module 3 damage/short-side outputs.
- `tests/test_m4_mean_reversion.py` — Unit tests for Module 4 mean-reversion outputs.
- `tests/test_m5_market_context.py` — Unit tests for Module 5 market-context outputs.
- `tests/test_v2_cache.py` — Stage 1 tests for schema, validation gate, and dry-run behavior.
- `tests/test_v2_factor_engine.py` — Stage 3 integration tests for writes, debug mode, and prefilter cache reuse.
- `tests/test_v2_orchestrator.py` — Stage 7 tests for ordering, abort/degrade logic, and log writes.
- `tests/test_v2_prefilter.py` — Stage 2 tests for filters, SPY survival, persistence, and exclusions.
- `tests/test_v2_risk_filters.py` — Stage 6 tests for config loading, math, sector caps, and writes.
- `tests/test_v2_selection.py` — Stage 5 tests for ranking, writes, beta clamp, and show-all behavior.
- `tests/test_v2_training_backfill.py` — Stage 4A tests for no-lookahead, label math, idempotence, and debug output.

## Common Usage Examples
- `python3 stages/v2_cache_warm.py --dry-run` — Stage 1 plan-only sanity check.
- `python3 stages/v2_factor_engine.py --dry-run --debug AAPL` — inspect one ticker’s factor vector.
- `python3 stages/v2_selection.py --dry-run --mock --show-all` — review the entire ranked universe without writing shortlist rows.
- `python3 stages/v2_risk_filters.py --size NVDA LONG --mock` — single-name sizing calculator.
- `python3 stages/v2_orchestrator.py --skip-cache --mock-ml --dry-run` — full pipeline smoke test.
- `python3 -c "from stages.tcn_scorer import TCNScorer; TCNScorer(); print('OK')"` — verify model loading.
- `curl -s http://localhost:8080/health` — API liveness check.
- `cd ui/signalstack-app && npm run build` — React production build smoke.

## Notes
- Tests under `tests/` are run with `python3 -m pytest ...`; they are not standalone CLIs.
- `stages/tcn_scorer.py` will only fully function once `models/tcn_pass_v1/model.pt` and `config.json` are present.
- The duplicate `download_extended_data.py` scripts are both live files; if behavior diverges, document which one you are using in runbooks.
