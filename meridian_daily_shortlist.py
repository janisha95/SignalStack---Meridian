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

    try:
        rows = [dict(r) for r in con.execute(
            """
            SELECT ticker, direction, tcn_long_score, tcn_short_score,
                   final_score, rank, regime, sector, price
            FROM shortlist_daily WHERE date = ?
            ORDER BY direction, final_score DESC
            """,
            (date,),
        ).fetchall()]
    except sqlite3.OperationalError:
        rows = [dict(r) for r in con.execute(
            """
            SELECT ticker, direction, tcn_score as tcn_long_score,
                   tcn_score as tcn_short_score,
                   final_score, rank, regime, sector, price
            FROM shortlist_daily WHERE date = ?
            ORDER BY direction, final_score DESC
            """,
            (date,),
        ).fetchall()]

    longs = [r for r in rows if r.get("direction") == "LONG"][:MAX_PICKS]
    shorts = [r for r in rows if r.get("direction") == "SHORT"][:MAX_PICKS]

    con.close()
    return {
        "date": date,
        "source": "meridian",
        "longs": longs,
        "shorts": shorts,
        "long_count": len(longs),
        "short_count": len(shorts),
    }


def write_shortlist(shortlist: dict, db_path: str = DB_PATH) -> int:
    con = sqlite3.connect(db_path)
    con.execute(
        """
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
        """
    )
    con.execute(
        "DELETE FROM meridian_shortlist_final WHERE run_date = ?",
        (shortlist["date"],),
    )
    now = datetime.now(_ET).isoformat()
    rank = 0
    for direction, picks in [("LONG", shortlist["longs"]), ("SHORT", shortlist["shorts"])]:
        for r in picks:
            rank += 1
            tcn = r.get("tcn_long_score") if direction == "LONG" else r.get("tcn_short_score")
            con.execute(
                """
                INSERT INTO meridian_shortlist_final
                (run_date, ticker, direction, tcn_score, final_score, rank,
                 regime, sector, price, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shortlist["date"],
                    r["ticker"],
                    direction,
                    tcn,
                    r.get("final_score"),
                    rank,
                    r.get("regime"),
                    r.get("sector"),
                    r.get("price"),
                    now,
                ),
            )
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
            print("    — No picks.")
            continue
        for i, r in enumerate(picks):
            tcn = r.get("tcn_long_score") if label == "LONG" else r.get("tcn_short_score")
            tcn_str = f"{tcn:.4f}" if tcn else "—"
            print(f"  {i+1:3d} {r['ticker']:>8} TCN={tcn_str} {(r.get('sector') or '—'):>10}")
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
