# STAGE 7: Orchestrator — v2_orchestrator.py

**Status:** SPEC COMPLETE — ready for build
**Depends on:** All stages 1-6

---

## What Stage 7 Does

Single script that chains all stages into a nightly pipeline. Runs at 5:00pm ET
daily. Also serves as a CLI entry point for running the full pipeline or
individual stages.

This is the glue. It doesn't compute anything — it calls stages in order,
checks success, handles failures, and reports results.

---

## Pipeline Flow

```
5:00 PM ET — Orchestrator starts

Step 1: Stage 1 (Cache warm)
  - Incremental by default, full-refresh on Monday or if DB stale
  - If FAIL → abort, send Telegram alert, exit

Step 2: Stage 2 (Prefilter)  
  - Reads from Stage 1 DB
  - Caches survivors to prefilter_results table
  - If FAIL → abort, send Telegram alert, exit

Step 3: Stage 3 (Factor Engine)
  - Uses cached prefilter results
  - Computes 34 factors for ~3k tickers
  - Writes factor_matrix_daily to DB
  - If FAIL → abort, send Telegram alert, exit

Step 4: Stage 4 (ML Scoring) — STUBBED until 4B trained
  - When stub: pass factor matrix through with mock predictions
  - When real: LightGBM + LSTM ensemble scoring
  - If FAIL → use mock predictions, warn, continue

Step 5: Stage 5 (Selection)
  - Ranks by residual alpha
  - Writes top 30 LONG + 30 SHORT candidates to shortlist_daily
  - If FAIL → warn, continue with empty shortlist

Step 6: Stage 6 (Risk Filters)
  - Sizes all candidates, checks FTMO rules
  - Writes to tradeable_portfolio, updates portfolio_state
  - If FAIL → warn, continue

Step 7: Report
  - Send Telegram summary
  - Write orchestrator_run to cache_meta
  - Print final summary

Total expected: ~6-8 minutes (cached prefilter + factors + scoring)
```

---

## 1. Input Contract

| Input | Source | Notes |
|-------|--------|-------|
| v2_universe.db | Stage 1 | Must exist |
| ALPACA_KEY, ALPACA_SECRET | Environment | For Stage 1 cache warm |
| config/risk_config.json | Stage 6 | Risk parameters |
| config/factor_registry.json | Stage 3 | Factor list |

### CLI Arguments

| Flag | Default | Notes |
|------|---------|-------|
| `--stage` | all | Run specific stage: 1,2,3,4,5,6 or "all" |
| `--skip-cache` | False | Skip Stage 1 (use existing DB data) |
| `--full-refresh` | False | Force Stage 1 full refresh |
| `--mock-ml` | True (until 4B trained) | Use mock predictions |
| `--dry-run` | False | Print what would happen, don't write |
| `--no-telegram` | False | Skip Telegram reports |
| `--prop-firm` | ftmo | Risk filter preset |
| `--debug` | None | Ticker to trace through all stages |

---

## 2. Output Contract

### Telegram Report (end of pipeline)

```
📊 Meridian Daily — Mar 26, 2026

Pipeline: ✅ completed in 7.2 min
Universe: 11,868 → 3,313 survivors → 34 factors

Top 10 LONG candidates:
 1. NVDA  +2.8%  Trending  Tech
 2. RRC   +2.1%  Trending  Energy
 3. WEN   +1.7%  Trending  Cons.Cyc
 ...

Top 10 SHORT candidates:
 1. SEDG  -1.9%  Choppy   Tech
 2. MHK   -1.5%  Volatile Ind.
 ...

Risk: 7/10 positions · Heat 4.2% · Daily 0.9% used
FTMO: all rules ✅

🌅 Market opens 9:30am ET
```

### DB Writes

- cache_meta: `orchestrator_run_at`, `orchestrator_status`, `orchestrator_elapsed`
- All stage-specific writes (factor_matrix_daily, shortlist_daily, etc.)

### orchestrator_log table

```sql
CREATE TABLE IF NOT EXISTS orchestrator_log (
    date TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,  -- OK, FAIL, SKIP, MOCK
    elapsed_seconds REAL,
    detail TEXT,           -- JSON with stage-specific info
    PRIMARY KEY (date, stage)
);
```

---

## 3. Implementation

```python
def run_pipeline(args):
    start = time.time()
    results = {}
    
    # Stage 1: Cache
    if not args.skip_cache:
        print(f"[orchestrator] Stage 1: Cache warm...", flush=True)
        try:
            from stages.v2_cache_warm import run_pipeline as cache_run
            cache_result = cache_run(cache_args)
            if not cache_result.get('ok'):
                abort("Stage 1 failed", cache_result)
            results['cache'] = {'status': 'OK', 'elapsed': ...}
        except Exception as e:
            abort(f"Stage 1 error: {e}")
    else:
        print(f"[orchestrator] Stage 1: SKIPPED (--skip-cache)", flush=True)
        results['cache'] = {'status': 'SKIP'}
    
    # Stage 2: Prefilter
    print(f"[orchestrator] Stage 2: Prefilter...", flush=True)
    try:
        from stages.v2_prefilter import run_prefilter
        prefilter_df = run_prefilter(db_path)
        survivors = len(prefilter_df)
        print(f"[orchestrator] Stage 2: {survivors} survivors", flush=True)
        results['prefilter'] = {'status': 'OK', 'survivors': survivors}
    except Exception as e:
        abort(f"Stage 2 error: {e}")
    
    # Stage 3: Factor Engine
    print(f"[orchestrator] Stage 3: Factor engine...", flush=True)
    # ... uses cached prefilter
    
    # Stage 4: ML Scoring (stub or real)
    if args.mock_ml:
        print(f"[orchestrator] Stage 4: MOCK predictions", flush=True)
        predictions = generate_mock_predictions(factor_matrix)
        results['ml'] = {'status': 'MOCK'}
    else:
        # Real ML scoring
        pass
    
    # Stage 5: Selection
    print(f"[orchestrator] Stage 5: Selection (top 30 + 30)...", flush=True)
    
    # Stage 6: Risk Filters
    print(f"[orchestrator] Stage 6: Risk filters ({args.prop_firm})...", flush=True)
    
    # Report
    elapsed = time.time() - start
    print(f"[orchestrator] DONE in {elapsed:.1f}s", flush=True)
    send_telegram_report(results)
    write_orchestrator_log(results)
```

### Debug Mode (--debug TICKER)

When `--debug AAPL` is passed, trace AAPL through every stage:

```
[orchestrator] Debug: tracing AAPL through all stages
[Stage 2] AAPL: PASS (price $252.61, vol $281M, 502 bars, regime CHOPPY)
[Stage 3] AAPL: 34 factors computed
  adx: 22.91, directional_conviction: -0.45, momentum_acceleration: 1.23, ...
[Stage 4] AAPL: predicted_return = +1.2% (mock)
[Stage 5] AAPL: residual_alpha = +0.8% (beta 1.15, rank #12 LONG)
[Stage 6] AAPL: APPROVED — 47 shares, stop $241.99, risk 0.5%
```

---

## 4. Failure Handling

| Stage | On Failure |
|-------|-----------|
| Stage 1 (Cache) | ABORT entire pipeline. Data is stale. |
| Stage 2 (Prefilter) | ABORT. Can't compute factors without universe. |
| Stage 3 (Factors) | ABORT. Can't score without factors. |
| Stage 4 (ML) | WARN + use mock predictions. Pipeline continues. |
| Stage 5 (Selection) | WARN + empty shortlist. Pipeline continues. |
| Stage 6 (Risk) | WARN + no sizing. Pipeline continues. |

Stages 1-3 are hard dependencies. Stages 4-6 degrade gracefully.

---

## 5. Scheduling

The orchestrator itself is a plain Python script. Scheduling via:

**macOS (launchd):**
```xml
<!-- ~/Library/LaunchAgents/com.signalstack.meridian.plist -->
<key>ProgramArguments</key>
<array>
    <string>/usr/bin/python3</string>
    <string>/Users/sjani008/SS/Meridian/stages/v2_orchestrator.py</string>
    <string>--skip-cache</string>  <!-- cache runs separately at 4:30pm -->
</array>
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key><integer>17</integer>
    <key>Minute</key><integer>0</integer>
</dict>
```

**Linux (cron):**
```
0 17 * * 1-5 cd /home/user/SS/Meridian && python3 stages/v2_orchestrator.py >> data/orchestrator.log 2>&1
```

---

## 6. Acceptance Criteria

- [ ] `stages/v2_orchestrator.py` exists
- [ ] Chains stages 1→2→3→4→5→6 in sequence
- [ ] --stage flag runs individual stages
- [ ] --skip-cache skips Stage 1
- [ ] --mock-ml uses mock predictions (default until 4B)
- [ ] --debug TICKER traces through all stages
- [ ] --dry-run prints plan without writing
- [ ] Stages 1-3 abort on failure
- [ ] Stages 4-6 degrade gracefully on failure
- [ ] Telegram report sent at end
- [ ] orchestrator_log table written
- [ ] Progress logging per OPERATIONAL_STANDARDS.md
- [ ] Total runtime < 10 minutes (cached prefilter)
- [ ] No S1 imports
- [ ] QA report at qa_report_stage7.md
