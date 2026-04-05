#!/usr/bin/env python3
"""v2_fundamental_enrichment.py — Enrich Meridian training_data with fundamental features.

Adds 15 new columns to training_data (10 yfinance fundamentals + 5 calendar features)
and re-exports the updated table to the NN_Sandbox CSV.

Fundamental features (Jansen Ch.4):
  market_cap_log, pe_ratio, pb_ratio, ps_ratio, dividend_yield,
  profit_margin, roe, debt_to_equity, beta, avg_volume_log

Calendar features:
  sector_encoded, month_of_year, day_of_week, quarter_end, days_to_month_end

Usage:
    python3 stages/v2_fundamental_enrichment.py           # full run
    python3 stages/v2_fundamental_enrichment.py --dry-run # fetch + enrich, no DB write
    python3 stages/v2_fundamental_enrichment.py --fetch-only  # fetch and cache, no DB update
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
STAGE_DIR      = Path(__file__).resolve().parent
REPO_ROOT      = STAGE_DIR.parent
DB_PATH        = REPO_ROOT / "data" / "v2_universe.db"
CACHE_PATH     = REPO_ROOT / "data" / "fundamental_cache.json"
CSV_OUT_PATH   = Path("/Users/sjani008/SS/NN_Sandbox/data/meridian_ALL_features.csv")

# ── Sector encoding ───────────────────────────────────────────────────────────
SECTOR_MAP: dict[str, int] = {
    "Technology": 0,
    "Healthcare": 1,
    "Financial Services": 2,
    "Consumer Cyclical": 3,
    "Communication Services": 4,
    "Industrials": 5,
    "Consumer Defensive": 6,
    "Energy": 7,
    "Utilities": 8,
    "Real Estate": 9,
    "Basic Materials": 10,
    "Unknown": 11,
}

# New columns this script manages (order matches ALTER TABLE / UPDATE)
NEW_COLUMNS = [
    "market_cap_log",
    "pe_ratio",
    "pb_ratio",
    "ps_ratio",
    "dividend_yield",
    "profit_margin",
    "roe",
    "debt_to_equity",
    "beta",
    "avg_volume_log",
    "sector_encoded",
    "month_of_year",
    "day_of_week",
    "quarter_end",
    "days_to_month_end",
]


# ── yfinance fetch ─────────────────────────────────────────────────────────────

def fetch_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """Fetch fundamental data for all tickers. Persist cache to JSON between runs."""
    try:
        import yfinance as yf
    except ImportError:
        print("[fund] ERROR: yfinance not installed — run: pip install yfinance", flush=True)
        sys.exit(1)

    # Load existing cache
    cache: dict[str, dict] = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text())
        except Exception:
            cache = {}

    missing = [t for t in tickers if t not in cache]
    print(
        f"[fund] {len(cache)} cached, {len(missing)} to fetch "
        f"({len(tickers)} total unique tickers)",
        flush=True,
    )

    for i, ticker in enumerate(missing, 1):
        try:
            info = yf.Ticker(ticker).info
            mc   = info.get("marketCap")
            avol = info.get("averageVolume")
            cache[ticker] = {
                "market_cap":     mc,
                "pe_ratio":       info.get("trailingPE"),
                "pb_ratio":       info.get("priceToBook"),
                "ps_ratio":       info.get("priceToSalesTrailing12Months"),
                "dividend_yield": info.get("dividendYield"),
                "profit_margin":  info.get("profitMargins"),
                "roe":            info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
                "beta":           info.get("beta"),
                "avg_volume":     avol,
                "sector":         info.get("sector", "Unknown") or "Unknown",
            }
        except Exception:
            cache[ticker] = {}  # empty dict — will be filled with NaN later

        if i % 100 == 0:
            pct = i * 100 // len(missing)
            print(f"[fund] Progress: {i}/{len(missing)} ({pct}%)", flush=True)
            CACHE_PATH.write_text(json.dumps(cache))
            time.sleep(0.1)

    # Final save
    CACHE_PATH.write_text(json.dumps(cache))
    print(f"[fund] Fetch complete. Cache saved → {CACHE_PATH}", flush=True)
    return cache


# ── Fundamental lookup helpers ────────────────────────────────────────────────

def _safe_log10(v: object) -> float | None:
    """log10 of a positive number, or None."""
    try:
        fv = float(v)  # type: ignore[arg-type]
        if fv > 0:
            return round(math.log10(fv), 6)
    except (TypeError, ValueError):
        pass
    return None


def _clip(v: object, lo: float, hi: float) -> float | None:
    """Clip a numeric value to [lo, hi], return None for non-numeric."""
    try:
        fv = float(v)  # type: ignore[arg-type]
        return max(lo, min(hi, fv))
    except (TypeError, ValueError):
        return None


def build_fundamental_row(cache_entry: dict) -> dict:
    """Convert raw cache dict to the 10 fundamental feature values."""
    mc  = cache_entry.get("market_cap")
    avol = cache_entry.get("avg_volume")

    pe = cache_entry.get("pe_ratio")
    # Negative P/E is meaningless as a signal — treat as missing
    if pe is not None:
        try:
            pe = float(pe)
            if pe < 0:
                pe = None
            elif pe > 200:
                pe = 200.0
        except (TypeError, ValueError):
            pe = None

    return {
        "market_cap_log":  _safe_log10(mc),
        "pe_ratio":        pe,
        "pb_ratio":        _clip(cache_entry.get("pb_ratio"),   0.0, 50.0),
        "ps_ratio":        _clip(cache_entry.get("ps_ratio"),   0.0, 50.0),
        "dividend_yield":  _clip(cache_entry.get("dividend_yield"), 0.0, 0.3),
        "profit_margin":   _clip(cache_entry.get("profit_margin"), -1.0, 1.0),
        "roe":             _clip(cache_entry.get("roe"),         -2.0, 5.0),
        "debt_to_equity":  _clip(cache_entry.get("debt_to_equity"), 0.0, 500.0),
        "beta":            _clip(cache_entry.get("beta"),        -3.0, 5.0),
        "avg_volume_log":  _safe_log10(avol),
    }


def build_calendar_row(date_str: str, sector: str) -> dict:
    """Compute the 5 calendar + sector features from a date string."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {k: None for k in ("sector_encoded", "month_of_year", "day_of_week", "quarter_end", "days_to_month_end")}

    # Last day of month
    if dt.month == 12:
        next_month_first = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        next_month_first = dt.replace(month=dt.month + 1, day=1)
    import calendar
    last_day = (next_month_first - __import__("datetime").timedelta(days=1)).day

    return {
        "sector_encoded":    SECTOR_MAP.get(sector, SECTOR_MAP["Unknown"]),
        "month_of_year":     dt.month,
        "day_of_week":       dt.weekday(),   # 0=Mon, 4=Fri
        "quarter_end":       1 if (dt.month in (3, 6, 9, 12) and dt.day >= last_day - 4) else 0,
        "days_to_month_end": last_day - dt.day,
    }


# ── Cross-sectional median fill ───────────────────────────────────────────────

def _median(values: list[float]) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2 == 0:
        return (vals[mid - 1] + vals[mid]) / 2.0
    return vals[mid]


def fill_cross_sectional_medians(
    rows: list[dict],
    fund_cols: list[str],
) -> list[dict]:
    """For each date, fill NULL fundamental values with that date's median."""
    from collections import defaultdict

    # Group by date
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)

    for date_rows in by_date.values():
        for col in fund_cols:
            vals = [r[col] for r in date_rows if r.get(col) is not None]
            med = _median(vals)
            if med is None:
                continue
            for r in date_rows:
                if r.get(col) is None:
                    r[col] = med

    return rows


# ── DB schema migration ───────────────────────────────────────────────────────

def ensure_new_columns(con: sqlite3.Connection) -> None:
    """ALTER TABLE to add any missing fundamental columns."""
    existing = {r[1] for r in con.execute("PRAGMA table_info(training_data)").fetchall()}
    added = 0
    for col in NEW_COLUMNS:
        if col not in existing:
            dtype = "INTEGER" if col in ("sector_encoded", "month_of_year", "day_of_week", "quarter_end", "days_to_month_end") else "REAL"
            con.execute(f'ALTER TABLE training_data ADD COLUMN "{col}" {dtype}')
            added += 1
    if added:
        con.commit()
        print(f"[fund] Added {added} new columns to training_data", flush=True)
    else:
        print("[fund] All columns already exist in training_data", flush=True)


# ── Main enrichment logic ─────────────────────────────────────────────────────

def run(dry_run: bool = False, fetch_only: bool = False) -> dict:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    # Step 1: Get all unique tickers
    print("[fund] Loading tickers from training_data...", flush=True)
    tickers = [r[0] for r in con.execute("SELECT DISTINCT ticker FROM training_data ORDER BY ticker").fetchall()]
    print(f"[fund] {len(tickers):,} unique tickers", flush=True)

    # Step 2: Fetch fundamentals (uses cache)
    cache = fetch_fundamentals(tickers)

    if fetch_only:
        con.close()
        print("[fund] --fetch-only: done. Cache ready for DB update.", flush=True)
        return {"ok": True, "fetch_only": True, "tickers": len(tickers)}

    # Step 3: Ensure columns exist
    if not dry_run:
        ensure_new_columns(con)

    # Step 4: Load training_data rows (chunked to manage memory)
    print("[fund] Enriching training_data with fundamentals...", flush=True)
    total_rows = con.execute("SELECT COUNT(*) FROM training_data").fetchone()[0]
    print(f"[fund] {total_rows:,} rows to enrich", flush=True)

    # Process in date chunks to keep memory reasonable
    dates = [r[0] for r in con.execute("SELECT DISTINCT date FROM training_data ORDER BY date").fetchall()]
    print(f"[fund] Processing {len(dates)} dates...", flush=True)

    rows_updated = 0
    CHUNK = 30  # dates per batch

    for chunk_start in range(0, len(dates), CHUNK):
        chunk_dates = dates[chunk_start:chunk_start + CHUNK]
        placeholders = ",".join("?" * len(chunk_dates))

        raw_rows = con.execute(
            f"SELECT rowid, ticker, date, sector FROM training_data WHERE date IN ({placeholders})",
            chunk_dates,
        ).fetchall()

        enriched: list[dict] = []
        for row in raw_rows:
            rowid   = row["rowid"]
            ticker  = row["ticker"]
            date    = row["date"]
            # Use sector from cache if available, else fall back to existing DB sector
            cache_entry = cache.get(ticker, {})
            sector  = cache_entry.get("sector") or row["sector"] or "Unknown"

            fund   = build_fundamental_row(cache_entry)
            cal    = build_calendar_row(date, sector)
            enriched.append({"rowid": rowid, "date": date, **fund, **cal})

        # Fill cross-sectional medians for fundamental columns only
        fund_cols = [c for c in NEW_COLUMNS if c not in (
            "sector_encoded", "month_of_year", "day_of_week", "quarter_end", "days_to_month_end"
        )]
        enriched = fill_cross_sectional_medians(enriched, fund_cols)

        if not dry_run:
            set_clause = ", ".join(f'"{c}" = ?' for c in NEW_COLUMNS)
            con.executemany(
                f'UPDATE training_data SET {set_clause} WHERE rowid = ?',
                [
                    tuple(r[c] for c in NEW_COLUMNS) + (r["rowid"],)
                    for r in enriched
                ],
            )
            con.commit()

        rows_updated += len(enriched)

        if (chunk_start // CHUNK + 1) % 10 == 0 or chunk_start + CHUNK >= len(dates):
            pct = min(100, (chunk_start + CHUNK) * 100 // len(dates))
            print(f"[fund] DB update progress: {pct}% ({rows_updated:,}/{total_rows:,} rows)", flush=True)

    con.close()

    if dry_run:
        print("[fund] DRY RUN — no DB writes performed", flush=True)
        return {"ok": True, "dry_run": True, "rows": rows_updated}

    # Step 5: Re-export CSV
    print(f"[fund] Re-exporting CSV → {CSV_OUT_PATH}", flush=True)
    CSV_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    con2 = sqlite3.connect(str(DB_PATH))
    import csv as _csv
    cursor = con2.execute("SELECT * FROM training_data")
    col_names = [d[0] for d in cursor.description]
    with open(CSV_OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = _csv.writer(f)
        writer.writerow(col_names)
        written = 0
        while True:
            batch = cursor.fetchmany(10_000)
            if not batch:
                break
            writer.writerows(batch)
            written += len(batch)
    con2.close()
    print(f"[fund] CSV exported: {written:,} rows × {len(col_names)} columns", flush=True)

    print(
        f"[fund] Done: {len(NEW_COLUMNS)} new columns added to {rows_updated:,} rows",
        flush=True,
    )
    return {
        "ok": True,
        "rows_updated": rows_updated,
        "new_columns": len(NEW_COLUMNS),
        "csv_path": str(CSV_OUT_PATH),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Enrich Meridian training_data with fundamental features")
    ap.add_argument("--dry-run",    action="store_true", help="Fetch + enrich in memory, no DB writes")
    ap.add_argument("--fetch-only", action="store_true", help="Only fetch and cache fundamentals, skip DB update")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", flush=True)
        return 1

    result = run(dry_run=args.dry_run, fetch_only=args.fetch_only)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
