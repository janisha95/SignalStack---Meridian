# CODEX — Complete Trade Pipeline: Shortlist → V6 Filters → Ultra.sh

## Context
S1 daily shortlist is built (`s1_daily_shortlist.py`, commit 483511f).
Meridian rebuild is live with dual TCN + bond ETF blocklist.
We need: Meridian shortlist extractor, V6 swing config, combined pipeline, and the master SH file.

Target: 3 prop firm accounts starting Monday Apr 7:
- TTP 20k Swing (S1 + Meridian picks, US equities, hold overnight OK)
- TTP 50k Intraday (Vanguard, US equities, close by EOD) — LATER
- GFT 5k Forex/CFD (Vanguard multi-asset) — LATER

This prompt builds the TTP 20k Swing pipeline only.

## Git backup
```bash
cd ~/SS/Advance && git add -A && git commit -m "backup: pre-trade-pipeline"
cd ~/SS/Meridian && git add -A && git commit -m "backup: pre-trade-pipeline"
cd ~/SS/Vanguard && git add -A && git commit -m "backup: pre-trade-pipeline"
```

---

## PART 1: Meridian Daily Shortlist Extractor

Create: `~/SS/Meridian/meridian_daily_shortlist.py`

Reads `shortlist_daily` from `v2_universe.db` for the latest date.
Takes top 5 LONG by tcn_long_score + top 5 SHORT by tcn_short_score.
Writes to a `meridian_shortlist_final` table (same DB).

```python
#!/usr/bin/env python3
"""
meridian_daily_shortlist.py — Extract top 5L + 5S from Meridian shortlist.

Reads shortlist_daily (post dual-TCN rebuild), takes top 5 per direction.
No additional threshold — the TCN scores ARE the ranking signal.

Usage:
  python3 meridian_daily_shortlist.py              # latest date
  python3 meridian_daily_shortlist.py --date 2026-04-01
  python3 meridian_daily_shortlist.py --dry-run
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DB_PATH = str(Path(__file__).resolve().parent / "data" / "v2_universe.db")
_ET = ZoneInfo("America/New_York")
MAX_PICKS = 5


def get_shortlist(date: str = "", db_path: str = DB_PATH) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    if not date:
        row = con.execute("SELECT MAX(date) FROM shortlist_daily").fetchone()
        date = row[0] if row and row[0] else ""
    if not date:
        con.close()
        return {"error": "No shortlist found"}

    # Try new schema first (tcn_long_score, tcn_short_score)
    try:
        rows = [dict(r) for r in con.execute("""
            SELECT ticker, direction, tcn_long_score, tcn_short_score,
                   final_score, rank, regime, sector, price
            FROM shortlist_daily WHERE date = ?
            ORDER BY direction, final_score DESC
        """, (date,)).fetchall()]
    except sqlite3.OperationalError:
        # Fallback to old schema
        rows = [dict(r) for r in con.execute("""
            SELECT ticker, direction, tcn_score as tcn_long_score,
                   tcn_score as tcn_short_score,
                   final_score, rank, regime, sector, price
            FROM shortlist_daily WHERE date = ?
            ORDER BY direction, final_score DESC
        """, (date,)).fetchall()]

    longs = [r for r in rows if r.get("direction") == "LONG"][:MAX_PICKS]
    shorts = [r for r in rows if r.get("direction") == "SHORT"][:MAX_PICKS]

    con.close()
    return {
        "date": date, "source": "meridian",
        "longs": longs, "shorts": shorts,
        "long_count": len(longs), "short_count": len(shorts),
    }


def write_shortlist(shortlist: dict, db_path: str = DB_PATH) -> int:
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS meridian_shortlist_final (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            tcn_score REAL,
            final_score REAL,
            rank INTEGER,
            regime TEXT,
            sector TEXT,
            price REAL,
            created_at TEXT NOT NULL
        )
    """)
    con.execute("DELETE FROM meridian_shortlist_final WHERE run_date = ?",
                (shortlist["date"],))
    now = datetime.now(_ET).isoformat()
    rank = 0
    for direction, picks in [("LONG", shortlist["longs"]), ("SHORT", shortlist["shorts"])]:
        for r in picks:
            rank += 1
            tcn = r.get("tcn_long_score") if direction == "LONG" else r.get("tcn_short_score")
            con.execute("""
                INSERT INTO meridian_shortlist_final
                (run_date, ticker, direction, tcn_score, final_score, rank,
                 regime, sector, price, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (shortlist["date"], r["ticker"], direction, tcn,
                  r.get("final_score"), rank, r.get("regime"),
                  r.get("sector"), r.get("price"), now))
    con.commit()
    con.close()
    return rank


def print_shortlist(sl: dict) -> None:
    print(f"\n{'='*55}")
    print(f"  MERIDIAN SHORTLIST — {sl['date']}")
    print(f"{'='*55}")
    for label, picks in [("LONG", sl["longs"]), ("SHORT", sl["shorts"])]:
        print(f"\n  {label} (top {MAX_PICKS}):")
        if not picks:
            print(f"    — No picks.")
            continue
        for i, r in enumerate(picks):
            tcn = r.get("tcn_long_score") if label == "LONG" else r.get("tcn_short_score")
            tcn_str = f"{tcn:.4f}" if tcn else "—"
            print(f"  {i+1:3d} {r['ticker']:>8} TCN={tcn_str} "
                  f"{(r.get('sector') or '—'):>10}")
    print(f"\n  Total: {sl['long_count']}L + {sl['short_count']}S\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sl = get_shortlist(date=args.date)
    if "error" in sl:
        print(f"ERROR: {sl['error']}")
        return 1
    print_shortlist(sl)
    if not args.dry_run:
        n = write_shortlist(sl)
        print(f"[meridian] {n} picks written to meridian_shortlist_final")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Test:
```bash
cd ~/SS/Meridian
python3 -m py_compile meridian_daily_shortlist.py
python3 meridian_daily_shortlist.py --dry-run
python3 meridian_daily_shortlist.py
```

---

## PART 2: V6 Swing Account Profile for TTP 20k

Check what the Vanguard account_profiles table looks like:
```bash
sqlite3 ~/SS/Vanguard/data/vanguard_universe.db "PRAGMA table_info(account_profiles)" 2>/dev/null || echo "Table doesn't exist"
sqlite3 ~/SS/Vanguard/data/vanguard_universe.db "SELECT * FROM account_profiles" 2>/dev/null || echo "No data"
```

Read the V6 spec to understand the schema:
```bash
cat ~/SS/Vanguard/stages/vanguard_stage6_risk.py 2>/dev/null | head -80
grep -rn "account_profile\|SWING\|INTRADAY\|max_position\|daily_loss\|max_drawdown" ~/SS/Vanguard/stages/ | head -20
```

If `account_profiles` exists, INSERT the TTP 20k Swing profile:
```sql
INSERT INTO account_profiles (
    account_name, account_type, asset_scope, max_positions,
    max_position_size_pct, daily_loss_limit, max_drawdown,
    holding_period, status, created_at
) VALUES (
    'TTP_20K_SWING',
    'swing',
    'us_equity',
    10,        -- max 10 open positions (5L + 5S)
    0.10,      -- max 10% per position ($2,000 on 20k)
    500.00,    -- daily loss limit $500 (2.5% of 20k)
    2000.00,   -- max drawdown $2,000 (10% of 20k — TTP limit)
    'overnight', -- can hold overnight (swing)
    'active',
    datetime('now')
);
```

If the table doesn't exist or the schema is different, read the V6 code first
and create the profile to match whatever schema V6 expects.

---

## PART 3: Combined Shortlist + V6 Filter Script

Create: `~/SS/signalstack_trade_pipeline.py`

This is the master script that:
1. Reads S1 daily shortlist from `signalstack_results.db.daily_shortlist`
2. Reads Meridian shortlist from `v2_universe.db.meridian_shortlist_final`
3. Combines them (dedup by ticker — if same ticker in both, keep higher conviction)
4. Runs combined list through V6 risk filters for TTP_20K_SWING account
5. Outputs final approved trades
6. Writes to a `trade_queue` table in a new `signalstack_trades.db`

```python
#!/usr/bin/env python3
"""
signalstack_trade_pipeline.py — Combine S1 + Meridian shortlists → V6 risk filters → trade queue.

Usage:
  python3 signalstack_trade_pipeline.py                    # full run
  python3 signalstack_trade_pipeline.py --dry-run          # print only
  python3 signalstack_trade_pipeline.py --account TTP_20K_SWING
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
SS_DIR = Path(__file__).resolve().parent

S1_DB = str(SS_DIR / "Advance" / "data_cache" / "signalstack_results.db")
MERIDIAN_DB = str(SS_DIR / "Meridian" / "data" / "v2_universe.db")
TRADES_DB = str(SS_DIR / "data" / "signalstack_trades.db")
VANGUARD_DB = str(SS_DIR / "Vanguard" / "data" / "vanguard_universe.db")

DEFAULT_ACCOUNT = "TTP_20K_SWING"


def load_s1_shortlist(date: str = "") -> list[dict]:
    """Load S1 daily shortlist."""
    if not Path(S1_DB).exists():
        return []
    con = sqlite3.connect(S1_DB)
    con.row_factory = sqlite3.Row
    if not date:
        row = con.execute("SELECT MAX(run_date) FROM daily_shortlist").fetchone()
        date = row[0] if row and row[0] else ""
    if not date:
        con.close()
        return []
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM daily_shortlist WHERE run_date = ? ORDER BY rank", (date,)
    ).fetchall()]
    con.close()
    for r in rows:
        r["source"] = "s1"
    return rows


def load_meridian_shortlist(date: str = "") -> list[dict]:
    """Load Meridian final shortlist."""
    if not Path(MERIDIAN_DB).exists():
        return []
    con = sqlite3.connect(MERIDIAN_DB)
    con.row_factory = sqlite3.Row
    if not date:
        row = con.execute("SELECT MAX(run_date) FROM meridian_shortlist_final").fetchone()
        date = row[0] if row and row[0] else ""
    if not date:
        con.close()
        return []
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM meridian_shortlist_final WHERE run_date = ? ORDER BY rank", (date,)
    ).fetchall()]
    con.close()
    for r in rows:
        r["source"] = "meridian"
        r["scorer_prob"] = r.get("tcn_score")  # normalize field name
    return rows


def combine_and_dedup(s1: list, meridian: list) -> list:
    """Combine S1 + Meridian, dedup by ticker+direction, keep higher score."""
    seen = {}
    for r in s1 + meridian:
        key = (r["ticker"], r["direction"])
        score = r.get("scorer_prob") or r.get("tcn_score") or r.get("final_score") or 0
        if key not in seen or score > (seen[key].get("_score") or 0):
            r["_score"] = score
            seen[key] = r
    combined = sorted(seen.values(), key=lambda x: (x["direction"], -(x.get("_score") or 0)))
    return combined


def apply_v6_filters(picks: list, account: str = DEFAULT_ACCOUNT) -> list:
    """Apply V6 risk filters for the given account profile."""
    # Load account profile
    if Path(VANGUARD_DB).exists():
        try:
            con = sqlite3.connect(VANGUARD_DB)
            con.row_factory = sqlite3.Row
            profile = con.execute(
                "SELECT * FROM account_profiles WHERE account_name = ?", (account,)
            ).fetchone()
            con.close()
            if profile:
                profile = dict(profile)
        except Exception:
            profile = None
    else:
        profile = None

    if not profile:
        # Default TTP 20k Swing limits
        profile = {
            "account_name": account,
            "asset_scope": "us_equity",
            "max_positions": 10,
            "max_position_size_pct": 0.10,
            "daily_loss_limit": 500.0,
            "max_drawdown": 2000.0,
            "holding_period": "overnight",
        }
        print(f"[v6] No DB profile for {account}, using defaults", flush=True)

    approved = []
    rejected = []
    for r in picks:
        # V6 check: asset scope
        # TTP only trades US equities — reject forex/crypto/ETFs if flagged
        # For now, all S1 and Meridian picks are US equities, so pass everything
        # Future: check against instrument type registry

        # V6 check: max positions per side
        side = r["direction"]
        same_side = [a for a in approved if a["direction"] == side]
        max_per_side = profile.get("max_positions", 10) // 2  # split evenly
        if len(same_side) >= max_per_side:
            r["v6_status"] = "REJECTED"
            r["v6_reason"] = f"max {max_per_side} positions per side"
            rejected.append(r)
            continue

        r["v6_status"] = "APPROVED"
        r["v6_reason"] = ""
        r["account"] = account
        approved.append(r)

    return approved, rejected


def write_trade_queue(approved: list, date: str) -> int:
    """Write approved trades to trade_queue table."""
    Path(TRADES_DB).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(TRADES_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS trade_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            source TEXT,
            scorer_prob REAL,
            tcn_score REAL,
            p_tp REAL,
            account TEXT,
            v6_status TEXT,
            strategy TEXT,
            regime TEXT,
            sector TEXT,
            price REAL,
            created_at TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_tq_date ON trade_queue(run_date)")
    con.execute("DELETE FROM trade_queue WHERE run_date = ?", (date,))

    now = datetime.now(_ET).isoformat()
    for r in approved:
        con.execute("""
            INSERT INTO trade_queue
            (run_date, ticker, direction, source, scorer_prob, tcn_score,
             p_tp, account, v6_status, strategy, regime, sector, price, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date, r["ticker"], r["direction"], r.get("source"),
            r.get("scorer_prob"), r.get("tcn_score"), r.get("p_tp"),
            r.get("account"), r.get("v6_status"), r.get("strategy"),
            r.get("regime"), r.get("sector"), r.get("price"), now,
        ))
    con.commit()
    con.close()
    return len(approved)


def print_pipeline(s1, meridian, combined, approved, rejected, date):
    print(f"\n{'='*65}")
    print(f"  SIGNALSTACK TRADE PIPELINE — {date}")
    print(f"{'='*65}")
    print(f"  S1:       {len(s1)} picks")
    print(f"  Meridian: {len(meridian)} picks")
    print(f"  Combined: {len(combined)} (deduped)")
    print(f"  Approved: {len(approved)}")
    print(f"  Rejected: {len(rejected)}")

    if approved:
        print(f"\n  APPROVED TRADES:")
        print(f"  {'#':>3} {'Ticker':>8} {'Dir':>6} {'Source':>8} {'Score':>7}")
        print(f"  {'-'*40}")
        for i, r in enumerate(approved):
            score = r.get("scorer_prob") or r.get("tcn_score") or 0
            print(f"  {i+1:3d} {r['ticker']:>8} {r['direction']:>6} "
                  f"{r.get('source', '?'):>8} {score:.4f}")

    if rejected:
        print(f"\n  REJECTED:")
        for r in rejected:
            print(f"    {r['ticker']} {r['direction']} — {r.get('v6_reason', '?')}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="")
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    s1 = load_s1_shortlist(date=args.date)
    meridian = load_meridian_shortlist(date=args.date)

    date = args.date or (s1[0]["run_date"] if s1 else
                         meridian[0]["run_date"] if meridian else
                         datetime.now(_ET).strftime("%Y-%m-%d"))

    combined = combine_and_dedup(s1, meridian)
    approved, rejected = apply_v6_filters(combined, account=args.account)

    print_pipeline(s1, meridian, combined, approved, rejected, date)

    if not args.dry_run and approved:
        n = write_trade_queue(approved, date)
        print(f"[pipeline] {n} trades written to trade_queue in {TRADES_DB}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Test:
```bash
cd ~/SS
python3 -m py_compile signalstack_trade_pipeline.py
python3 signalstack_trade_pipeline.py --dry-run
```

---

## PART 4: Ultra.sh — The Master Script

Create: `~/SS/ultra.sh`

```bash
#!/bin/bash
# SignalStack Ultra — Master pipeline runner
# Does EVERYTHING: health check, servers, orchestrators, shortlists, trade queue
#
# Usage:
#   ~/SS/ultra.sh              — full evening run (default)
#   ~/SS/ultra.sh --status     — health check only
#   ~/SS/ultra.sh --shortlist  — shortlist + trade queue only (skip orchestrators)

set -e
LOG_DIR=~/SS/logs
LOG=$LOG_DIR/ultra_$(date +%Y%m%d).log
mkdir -p "$LOG_DIR"
PY=/opt/homebrew/bin/python3

_log() { echo "$(date '+%H:%M:%S') $1" | tee -a "$LOG"; }

# Weekend check
DOW=$(date +%u)
if [ "$DOW" -ge 6 ]; then
    _log "Weekend (day=$DOW), skipping"
    exit 0
fi

MODE="${1:---full}"

# ── HEALTH CHECK ──────────────────────────────────────────────────────────────
_log "=== HEALTH CHECK ==="

~/SS/servers.sh status 2>&1 | tee -a "$LOG"

# Start servers if not running
_log "Starting any stopped services..."
~/SS/servers.sh start 2>&1 | tee -a "$LOG"
sleep 3

if [ "$MODE" = "--status" ]; then
    _log "Status check complete."
    exit 0
fi

# ── FUC CACHE UPDATE ──────────────────────────────────────────────────────────
if [ "$MODE" = "--full" ]; then
    _log "=== FUC CACHE UPDATE ==="
    cd ~/SS/Advance && $PY fast_universe_cache.py \
        --update \
        --db /Users/sjani008/SS/SignalStack8/data_cache/universe_ohlcv.db \
        >> "$LOG_DIR/cache.log" 2>&1
    _log "FUC cache done (exit=$?)"
fi

# ── MERIDIAN ORCHESTRATOR ─────────────────────────────────────────────────────
if [ "$MODE" = "--full" ]; then
    _log "=== MERIDIAN PIPELINE ==="
    cd ~/SS/Meridian && $PY stages/v2_orchestrator.py --skip-cache --real-ml 2>&1 | tee -a "$LOG"
    _log "Meridian done (exit=$?)"
fi

# ── S1 EVENING PIPELINE ──────────────────────────────────────────────────────
if [ "$MODE" = "--full" ]; then
    _log "=== S1 EVENING SCAN ==="
    cd ~/SS/Advance && $PY s1_orchestrator_v2.py --stage evening 2>&1 | tee -a "$LOG"
    _log "S1 evening done (exit=$?)"

    _log "=== S1 NIGHT EXPANSION ==="
    cd ~/SS/Advance && $PY s1_orchestrator_v2.py --stage night 2>&1 | tee -a "$LOG"
    _log "S1 night done (exit=$?)"
fi

# ── SCORER ────────────────────────────────────────────────────────────────────
_log "=== S1 SCORER ==="
cd ~/SS/Advance && $PY s1_pass_scorer.py --score 2>&1 | tee -a "$LOG"
_log "Scorer done (exit=$?)"

# ── SHORTLISTS ────────────────────────────────────────────────────────────────
_log "=== S1 DAILY SHORTLIST ==="
cd ~/SS/Advance && $PY s1_daily_shortlist.py 2>&1 | tee -a "$LOG"
_log "S1 shortlist done"

_log "=== MERIDIAN DAILY SHORTLIST ==="
cd ~/SS/Meridian && $PY meridian_daily_shortlist.py 2>&1 | tee -a "$LOG"
_log "Meridian shortlist done"

# ── TRADE PIPELINE (COMBINE + V6 FILTERS) ────────────────────────────────────
_log "=== TRADE PIPELINE ==="
cd ~/SS && $PY signalstack_trade_pipeline.py --account TTP_20K_SWING 2>&1 | tee -a "$LOG"
_log "Trade pipeline done"

_log "=== ULTRA COMPLETE ==="
_log "Log: $LOG"
```

Install:
```bash
chmod +x ~/SS/ultra.sh
```

Test:
```bash
# Shortlist only (skip orchestrators — use existing data)
~/SS/ultra.sh --shortlist

# Full run (orchestrators + shortlists + trade queue)
~/SS/ultra.sh
```

---

## Verification

```bash
# All files compile
python3 -m py_compile ~/SS/Meridian/meridian_daily_shortlist.py
python3 -m py_compile ~/SS/signalstack_trade_pipeline.py

# Test shortlist-only mode
cd ~/SS/Advance && python3 s1_daily_shortlist.py --dry-run
cd ~/SS/Meridian && python3 meridian_daily_shortlist.py --dry-run
cd ~/SS && python3 signalstack_trade_pipeline.py --dry-run
```

## Commits
```bash
cd ~/SS/Meridian && git add -A && git commit -m "feat: meridian daily shortlist extractor"
cd ~/SS && git add signalstack_trade_pipeline.py ultra.sh && git commit -m "feat: combined trade pipeline + ultra.sh"
```
