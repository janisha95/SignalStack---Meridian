# STAGE 1: Cache Pipeline — v2_cache_warm.py

**Status:** SPEC APPROVED — ready for build
**Reviewed by:** GPT (4 edits applied) + Shan (approved)

---

## What Stage 1 Does

Single automated job that pulls ALL market data sources in sequence, validates alignment, and signals the orchestrator to proceed. Meridian has its OWN database — no cross-stack sharing with S1 or S8.

Runs daily at 4:30pm ET (before Stage 2 prefilter at 5:00pm ET).

---

## 1. Input Contract

### Required Inputs

| Input | Source | Format | Notes |
|---|---|---|---|
| Alpaca API credentials | Env vars | `ALPACA_KEY`, `ALPACA_SECRET` | Pipeline aborts if missing |
| YF universe diff file | `yf_universe_diff.txt` in repo root or ~/SS/Advance/ | Text file, one ticker per line, ~6,073 tickers | Source of YF-only tickers |
| Sector map | `config/ticker_sector_map.json` | JSON dict `{"AAPL": "Technology"}` | 621 tickers, 11 GICS sectors |
| v2 DB path | Env var or default | `V2_DB_PATH`, default: `~/SS/Meridian/data/v2_universe.db` | Created if not exists |

### Bootstrap-Only Input (temporary dependency)

| Input | Source | Notes |
|---|---|---|
| FUC DB | `~/SS/SignalStack8/data_cache/universe_ohlcv.db` | **Bootstrap only.** Read Alpaca ticker list for initial seed. Once Meridian's own cache is established via its own Alpaca API calls, this dependency is removed. Meridian must NOT depend on S8 for ongoing operation. |

### Optional Inputs

| Input | Default | Notes |
|---|---|---|
| `--dry-run` | False | Print plan, no downloads |
| `--skip-alpaca` | False | Skip Alpaca step |
| `--skip-yf` | False | Skip YF step |
| `--skip-options` | False | Skip options chain pull |
| `--days N` | 5 | Incremental: fetch stale tickers |
| `--full-refresh` | False | Download 2 years of history |

### Assumptions

- Alpaca API reachable (paper or live)
- Internet access for yfinance
- ~/SS/Meridian/data/ will be created if not exists

### Forbidden / Invalid Input

- Missing ALPACA_KEY or ALPACA_SECRET → hard abort
- v2 DB path pointing to S1 or S8 databases → reject
- Stale Alpaca credentials (HTTP 401) → hard abort after 3 retries

---

## 2. Output Contract

### Primary Output: Meridian SQLite Database

**File:** `~/SS/Meridian/data/v2_universe.db`

#### Table: daily_bars

| Column | Type | Constraints |
|---|---|---|
| ticker | TEXT | NOT NULL |
| date | TEXT | NOT NULL, ISO YYYY-MM-DD |
| open | REAL | |
| high | REAL | |
| low | REAL | |
| close | REAL | |
| volume | REAL | |
| source | TEXT | alpaca_bars_nightly / yfinance_v2 / yfinance_futures |
| PRIMARY KEY | | (ticker, date) |

Indexes: idx_v2_ticker_date, idx_v2_source, idx_v2_date

#### Table: options_daily

| Column | Type | Notes |
|---|---|---|
| ticker | TEXT | NOT NULL |
| date | TEXT | NOT NULL |
| pcr | REAL | Put/Call ratio |
| unusual_vol_ratio | REAL | Best-effort / approximate v1 |
| net_delta | REAL | Best-effort / approximate v1 |
| source | TEXT | yahoo_options |
| PRIMARY KEY | | (ticker, date) |

#### Table: cache_meta

| Column | Type | Notes |
|---|---|---|
| key | TEXT PRIMARY KEY | e.g., last_alpaca_warm |
| value | TEXT | ISO timestamp or count |
| updated_at | TEXT | ISO timestamp |

DB settings: WAL mode, busy_timeout=5000ms

### Secondary Output: cache_warm_report.json

Written to ~/SS/Meridian/data/. Contains per-step results, timing, universe summary.

### Who Consumes This Output

- Stage 2 (Prefilter): reads daily_bars
- Stage 3 (Factor Engine): reads daily_bars + options_daily
- Stage 7 (Orchestrator): reads cache_meta to verify warm

---

## 3. Success Test

### Smoke Test

```bash
cd ~/SS/Meridian
python3 stages/v2_cache_warm.py --dry-run
# Should print step-by-step plan without writing data
```

### Unit Tests (test_v2_cache.py)

1. DB created with 3 tables (daily_bars, options_daily, cache_meta)
2. Alpaca step writes 7,500+ tickers
3. SPY present with latest date >= most recent trading day
4. No >50% single-day price jumps (validation gate)
5. YF step writes rows with source=yfinance_v2, no NULL dates, count >= 100
6. Options step writes PCR data for 500+ tickers
7. cache_meta timestamps updated

### Expected Ranges

| Metric | Expected | Red Flag |
|---|---|---|
| Alpaca tickers | 7,500-9,000 | < 5,000 |
| YF diff fetched | 500-4,000 | 0 |
| Options pulled | 700-1,000 | < 500 |
| Total tickers | 10,000-12,000 | < 8,000 |
| SPY latest | Most recent trading day | > 1 trading day stale |
| Elapsed | 10-20 minutes | > 30 minutes |

---

## 4. Fail Condition

### Hard Fail (abort pipeline)

| Condition | Action |
|---|---|
| ALPACA_KEY or ALPACA_SECRET not set | Exit code 1 |
| Alpaca API 401/403 after 3 retries | Exit code 1 |
| SPY missing from DB after warm | Abort |
| SPY latest > 1 trading day stale (accounting for weekends/holidays via get_last_trading_day() helper) | Abort |
| >100 tickers with >50% daily price jump | Abort (data corruption) |
| v2 DB path collides with S1/S8 | Abort |
| Validation gate fails any check | Abort, write FAIL to cache_meta |

### Soft Warning (log + continue)

| Condition | Action |
|---|---|
| YF cache returns 0 tickers | Warn, continue |
| Options pull < 50% success | Warn, continue |
| Alpaca count < 7,500 | Warn, continue |
| Individual ticker failure | Log, skip, continue |
| Elapsed > 20 minutes | Warn |

---

## Implementation Blueprint

### Copy from S1:
- `fast_universe_cache.py` → Alpaca bars logic (write to Meridian DB, use ALPACA_KEY)
- `yf_cache_pipeline.py` → YF diff download (write to Meridian DB, source: yfinance_v2)

### New code:
- `step_options_pull()` — batch yf.Ticker(t).options for top 1000 by dollar volume
- `step_validation_gate()` — SPY date check, price jump scan, alignment check
- `_ensure_v2_db()` — create all 3 tables + indexes, WAL mode
- CLI with argparse (--dry-run, --skip-*, --days, --full-refresh)

### Output file: `~/SS/Meridian/stages/v2_cache_warm.py`

---

## Acceptance Criteria

- [ ] `stages/v2_cache_warm.py` exists and runs without errors
- [ ] `data/v2_universe.db` created with 3 tables
- [ ] Alpaca step writes 7,500+ tickers
- [ ] YF step writes 500+ diff tickers
- [ ] Options step writes PCR for 500+ tickers
- [ ] Validation gate checks SPY date, price jumps, alignment
- [ ] Validation gate ABORTS if SPY missing or stale
- [ ] cache_warm_report.json written
- [ ] cache_meta updated with timestamps
- [ ] --dry-run prints plan without writing
- [ ] All unit tests pass
- [ ] ast.parse() passes
- [ ] No imports from S1 agent_server.py
- [ ] v2 DB does NOT point to S1/S8
- [ ] **Idempotent:** Re-running does not duplicate rows (INSERT OR REPLACE)
- [ ] **Performance:** Incremental warm within 20 minutes
