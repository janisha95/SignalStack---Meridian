# Meridian Debug Commands
All commands assume `cd /Users/sjani008/SS/Meridian`. Commands are read-only unless explicitly noted.
## Global Health Checks
```bash
python3 - <<'PY'
import sqlite3
con = sqlite3.connect('data/v2_universe.db')
for table in ['daily_bars','options_daily','prefilter_results','factor_matrix_daily','factor_history','training_data','shortlist_daily','tradeable_portfolio','portfolio_state','orchestrator_log']:
    try:
        count = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        date_cols = [r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()]
        if "date" in date_cols:
            mn, mx = con.execute(f'SELECT MIN(date), MAX(date) FROM {table}').fetchone()
            print(f'{table:20s} rows={count:,} dates={mn}..{mx}')
        else:
            print(f'{table:20s} rows={count:,}')
    except Exception as e:
        print(f'{table:20s} ERROR {e}')
con.close()
PY
```
## 1 Cache Warm
- `python3 stages/v2_cache_warm.py --dry-run` — print the plan without writing or requiring Alpaca credentials.
- `python3 stages/v2_cache_warm.py --full-refresh` — rebuild 2 years of history with progress logging.
- `python3 - <<'PY'
import sqlite3
con=sqlite3.connect('data/v2_universe.db')
print(con.execute("SELECT COUNT(*), COUNT(DISTINCT ticker), MIN(date), MAX(date) FROM daily_bars").fetchone())
print('SPY latest:', con.execute("SELECT MAX(date) FROM daily_bars WHERE ticker='SPY'").fetchone()[0])
print('validation_status:', con.execute("SELECT value FROM cache_meta WHERE key='stage1_validation_status'").fetchone())
con.close()
PY`
- Common failures: missing `ALPACA_KEY`/`ALPACA_SECRET`, SPY stale, or a hard validation abort. Check `data/cache_warm_report.json` and `cache_meta` keys first.

## 2 Prefilter
- `python3 stages/v2_prefilter.py --dry-run` — compute survivors without writing cache/meta rows.
- `python3 stages/v2_prefilter.py --min-price 2 --min-dollar-volume 1000000 --min-bars 50` — explicit production thresholds.
- `python3 - <<'PY'
import sqlite3
con=sqlite3.connect('data/v2_universe.db')
print('validation_status:', con.execute("SELECT value FROM cache_meta WHERE key='stage1_validation_status'").fetchone())
print('prefilter latest:', con.execute("SELECT MAX(date), COUNT(*) FROM prefilter_results").fetchone())
con.close()
PY`
- Common failures: missing Stage 1 PASS status, empty `daily_bars`, or too-aggressive thresholds.

## 3 Factor Engine
- `python3 stages/v2_factor_engine.py --dry-run` — compute the matrix without writes.
- `python3 stages/v2_factor_engine.py --dry-run --debug AAPL` — print factor values for one ticker.
- `python3 - <<'PY'
import sqlite3
con=sqlite3.connect('data/v2_universe.db')
print('factor_matrix latest/count:', con.execute("SELECT MAX(date), COUNT(*) FROM factor_matrix_daily").fetchone())
print('prefilter cache:', con.execute("SELECT value FROM cache_meta WHERE key='prefilter_run_at'").fetchone())
con.close()
PY`
- Common failures: factor registry mismatch, stale/missing prefilter cache when `--skip-prefilter` is used, or performance regressions when Stage 2 reruns unexpectedly.

## 4A Training Backfill
- `python3 stages/v2_training_backfill.py --dry-run --sample 50` — one-batch smoke test.
- `python3 stages/v2_training_backfill.py --debug AAPL --start-date 2025-01-02 --end-date 2025-01-10` — inspect historical factor rows and labels.
- `python3 - <<'PY'
import sqlite3
con=sqlite3.connect('data/v2_universe.db')
print(con.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM training_data").fetchone())
con.close()
PY`
- Common failures: insufficient warmup history, slow runtime from full-date sweeps, or accidental look-ahead if you modify the slicing logic.

## 4B TCN Scorer
- `python3 -c "from stages.tcn_scorer import TCNScorer; s = TCNScorer(); print('OK')"` — verify the model/config load.
- `python3 - <<'PY'
from stages.tcn_scorer import TCNScorer
s=TCNScorer()
print(s.score('2026-03-18').head())
PY`
- `python3 - <<'PY'
import sqlite3
con=sqlite3.connect('data/v2_universe.db')
print(con.execute("SELECT COUNT(*), COUNT(DISTINCT date) FROM factor_history").fetchone())
con.close()
PY`
- Common failures: missing `models/tcn_pass_v1/model.pt`, insufficient `factor_history` depth (<64 dates), or mismatched state_dict key names after architecture edits.

## 5 Selection
- `python3 stages/v2_selection.py --dry-run --mock` — factor-only shortlist generation with mock predictions.
- `python3 stages/v2_selection.py --show-all --mock` — inspect the entire ranked universe instead of just top-N per side.
- `python3 - <<'PY'
import sqlite3
con=sqlite3.connect('data/v2_universe.db')
print(con.execute("SELECT MAX(date), COUNT(*) FROM shortlist_daily").fetchone())
print(con.execute("SELECT ticker, direction, final_score, tcn_score FROM shortlist_daily ORDER BY date DESC, direction, rank LIMIT 10").fetchall())
con.close()
PY`
- Common failures: no `predictions_daily` when not using `--mock`, empty prefilter cache, or missing model files if you expect non-neutral TCN scores.

## 6 Risk Filters
- `python3 stages/v2_risk_filters.py --dry-run --mock --prop-firm ftmo` — evaluate the current shortlist with mock stage inputs.
- `python3 stages/v2_risk_filters.py --size AAPL LONG --mock` — sizing calculator for one name.
- `python3 stages/v2_risk_filters.py --tickers AAPL,MSFT --directions LONG,LONG --dry-run` — manual candidate review mode.
- `python3 - <<'PY'
import sqlite3
con=sqlite3.connect('data/v2_universe.db')
for t in ['tradeable_portfolio','portfolio_state','trade_log']:
    try: print(t, con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
    except Exception as e: print(t, e)
con.close()
PY`
- Common failures: empty shortlist, sector/correlation caps eliminating everything, or confusing dry-run expectations (it still computes, it just avoids persisting writes).

## 7 Orchestrator
- `python3 stages/v2_orchestrator.py --skip-cache --mock-ml --dry-run` — end-to-end smoke without Stage 1 writes.
- `python3 stages/v2_orchestrator.py --stage 3 --dry-run` — isolate one stage by number or `all`.
- `python3 stages/v2_orchestrator.py --skip-cache --mock-ml --debug AAPL` — trace one ticker through the pipeline.
- `python3 - <<'PY'
import sqlite3
con=sqlite3.connect('data/v2_universe.db')
print(con.execute("SELECT date, stage, status, elapsed_seconds FROM orchestrator_log ORDER BY rowid DESC LIMIT 20").fetchall())
con.close()
PY`
- Common failures: Stage 1-3 hard dependency aborts, silent degrade in Stage 4-6 if you are not reading `orchestrator_log`, or stale predictions/factor-history assumptions.

## API + Frontend
- `python3 stages/v2_api_server.py --port 8080` — start the API server.
- `curl -s http://localhost:8080/health | python3 -m json.tool`
- `curl -s http://localhost:8080/api/v2/scan | python3 -m json.tool | head -40`
- `curl -s http://localhost:8080/api/model/health | python3 -m json.tool`
- `curl -s -X POST http://localhost:8080/api/risk/size -H 'Content-Type: application/json' -d '{"ticker":"AAPL","direction":"LONG"}' | python3 -m json.tool`
- `cd ui/signalstack-app && npm run build` — production build smoke for the Next.js app.
- Common failures: missing tables produce empty payloads by design, while `/api/v2/ticker/{ticker}` depends on yfinance/network and may return a shaped error payload.

## Error Diagnosis Guide
- **Empty shortlist:** Check `prefilter_results`, `predictions_daily`, then `shortlist_daily` in that order. Empty upstream tables usually propagate cleanly.
- **Neutral TCN everywhere (`0.5`):** Model files are missing or the scorer could not build 64-day sequences from `factor_history`.
- **API returns 200 but empty arrays:** Usually a missing or empty source table, not a server crash. Inspect the matching table with SQLite first.
- **React page looks live but metrics are blank/empty:** The UI intentionally shows empty-state panels when the backend does not provide real series yet. Check `/api/model/health`, `/api/model/factors`, `/api/trades/log`, and `/api/positions`.
- **ET/UTC freshness mismatch:** Meridian now uses ET helpers for trading-day logic; if freshness still looks wrong, inspect `cache_meta` timestamps and confirm the script path is using `now_et_iso()` / `today_et()`.
