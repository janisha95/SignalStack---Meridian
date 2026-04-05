#!/usr/bin/env python3
"""
v2_forward_tracker.py — Forward-tracking validation for pick quality.

Records daily picks with entry prices and evaluates TBM outcomes after 5 trading days.
WIN  = +2% TP hit
LOSE = -1% SL hit
TIMEOUT = neither within 5 days (use actual return at close)

CLI:
  python3 stages/v2_forward_tracker.py --evaluate
  python3 stages/v2_forward_tracker.py --backfill --start-date 2026-03-20
  python3 stages/v2_forward_tracker.py --summary
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "v2_universe.db"

TP_PCT = 0.02   # +2% take profit
SL_PCT = 0.01   # -1% stop loss
EVAL_WINDOW = 5  # trading days


# ── DB helpers ────────────────────────────────────────────────────────────────

def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def ensure_table(db_path: Path) -> None:
    con = _connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS pick_tracking (
                pick_date TEXT NOT NULL,
                eval_date TEXT,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                tcn_score REAL,
                factor_rank REAL,
                final_score REAL,
                residual_alpha REAL,
                rank INTEGER,
                outcome TEXT,
                exit_price REAL,
                exit_date TEXT,
                return_pct REAL,
                days_held INTEGER,
                hit_tp_first INTEGER,
                regime TEXT,
                sector TEXT,
                beta REAL,
                PRIMARY KEY (pick_date, ticker)
            );

            CREATE INDEX IF NOT EXISTS idx_pt_outcome
                ON pick_tracking(outcome);
            CREATE INDEX IF NOT EXISTS idx_pt_direction
                ON pick_tracking(direction);
            CREATE INDEX IF NOT EXISTS idx_pt_pick_date
                ON pick_tracking(pick_date);
            """
        )
        con.commit()
    finally:
        con.close()


# ── Snapshot (insert today's picks) ──────────────────────────────────────────

def snapshot_picks(db_path: Path, pick_date: str | None = None) -> int:
    """Insert shortlist_daily rows for pick_date into pick_tracking with outcome=PENDING.

    Returns number of rows inserted (skips rows already tracked for that date).
    """
    con = _connect(db_path)
    try:
        if pick_date is None:
            row = con.execute(
                "SELECT MAX(date) as d FROM shortlist_daily"
            ).fetchone()
            pick_date = row["d"] if row and row["d"] else None
        if not pick_date:
            return 0

        rows = con.execute(
            """
            SELECT ticker, direction, price, tcn_score, factor_rank,
                   final_score, residual_alpha, rank, regime, sector, beta
            FROM shortlist_daily
            WHERE date = ?
            """,
            (pick_date,),
        ).fetchall()

        if not rows:
            return 0

        inserted = 0
        for r in rows:
            entry_price = r["price"]
            if not entry_price or entry_price <= 0:
                continue
            try:
                con.execute(
                    """
                    INSERT OR IGNORE INTO pick_tracking (
                        pick_date, ticker, direction, entry_price,
                        tcn_score, factor_rank, final_score, residual_alpha,
                        rank, regime, sector, beta,
                        outcome
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (
                        pick_date,
                        r["ticker"],
                        r["direction"],
                        entry_price,
                        r["tcn_score"],
                        r["factor_rank"],
                        r["final_score"],
                        r["residual_alpha"],
                        r["rank"],
                        r["regime"],
                        r["sector"],
                        r["beta"],
                    ),
                )
                if con.execute("SELECT changes()").fetchone()[0] > 0:
                    inserted += 1
            except sqlite3.Error:
                continue
        con.commit()
        return inserted
    finally:
        con.close()


# ── Evaluation logic ──────────────────────────────────────────────────────────

def evaluate_pick(
    ticker: str,
    direction: str,
    entry_price: float,
    ohlcv_5d: pd.DataFrame,
) -> dict[str, Any]:
    """Check if pick hit TBM targets within 5 trading days.

    Args:
        ticker: stock ticker (used for error messages only)
        direction: 'LONG' or 'SHORT'
        entry_price: close price on pick date
        ohlcv_5d: DataFrame indexed by date with columns [open, high, low, close, volume]
                  Must contain the trading days AFTER pick_date (not including it).

    Returns:
        dict with outcome, exit_price, exit_date, return_pct, days_held, hit_tp_first
    """
    for i, (dt, row) in enumerate(ohlcv_5d.iterrows()):
        if direction == "LONG":
            if row["high"] >= entry_price * (1 + TP_PCT):
                return {
                    "outcome": "WIN",
                    "exit_price": round(entry_price * (1 + TP_PCT), 4),
                    "exit_date": str(dt)[:10],
                    "return_pct": TP_PCT,
                    "days_held": i + 1,
                    "hit_tp_first": 1,
                }
            if row["low"] <= entry_price * (1 - SL_PCT):
                return {
                    "outcome": "LOSE",
                    "exit_price": round(entry_price * (1 - SL_PCT), 4),
                    "exit_date": str(dt)[:10],
                    "return_pct": -SL_PCT,
                    "days_held": i + 1,
                    "hit_tp_first": 0,
                }
        else:  # SHORT
            if row["low"] <= entry_price * (1 - TP_PCT):
                return {
                    "outcome": "WIN",
                    "exit_price": round(entry_price * (1 - TP_PCT), 4),
                    "exit_date": str(dt)[:10],
                    "return_pct": TP_PCT,
                    "days_held": i + 1,
                    "hit_tp_first": 1,
                }
            if row["high"] >= entry_price * (1 + SL_PCT):
                return {
                    "outcome": "LOSE",
                    "exit_price": round(entry_price * (1 + SL_PCT), 4),
                    "exit_date": str(dt)[:10],
                    "return_pct": -SL_PCT,
                    "days_held": i + 1,
                    "hit_tp_first": 0,
                }

    # Neither hit within the window — TIMEOUT
    last_close = float(ohlcv_5d.iloc[-1]["close"])
    if direction == "LONG":
        actual_return = (last_close - entry_price) / entry_price
    else:
        actual_return = (entry_price - last_close) / entry_price

    return {
        "outcome": "TIMEOUT",
        "exit_price": round(last_close, 4),
        "exit_date": str(ohlcv_5d.index[-1])[:10],
        "return_pct": round(actual_return, 6),
        "days_held": len(ohlcv_5d),
        "hit_tp_first": 0,
    }


def _get_trading_days_after(con: sqlite3.Connection, pick_date: str, n: int) -> list[str]:
    """Return up to n distinct trading days in daily_bars that come after pick_date."""
    rows = con.execute(
        """
        SELECT DISTINCT date FROM daily_bars
        WHERE date > ?
        ORDER BY date ASC
        LIMIT ?
        """,
        (pick_date, n),
    ).fetchall()
    return [r["date"] for r in rows]


def _load_ohlcv(con: sqlite3.Connection, ticker: str, dates: list[str]) -> pd.DataFrame:
    if not dates:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(dates))
    rows = con.execute(
        f"""
        SELECT date, open, high, low, close, volume
        FROM daily_bars
        WHERE ticker = ? AND date IN ({placeholders})
        ORDER BY date ASC
        """,
        [ticker, *dates],
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df = df.set_index("date")
    return df


def _evaluate_pending(db_path: Path, since_date: str | None = None) -> dict[str, Any]:
    """Evaluate all PENDING picks that have 5+ trading days of data available."""
    ensure_table(db_path)
    con = _connect(db_path)
    try:
        # Find latest trading day we have data for
        latest_bar_date = con.execute(
            "SELECT MAX(date) as d FROM daily_bars"
        ).fetchone()["d"]
        if not latest_bar_date:
            return {"evaluated": 0, "error": "No OHLCV data"}

        query = "SELECT * FROM pick_tracking WHERE outcome = 'PENDING'"
        params: list[Any] = []
        if since_date:
            query += " AND pick_date >= ?"
            params.append(since_date)
        pending = con.execute(query, params).fetchall()

        evaluated = 0
        skipped = 0

        for pick in pending:
            pick_date = pick["pick_date"]
            ticker = pick["ticker"]
            direction = pick["direction"]
            entry_price = float(pick["entry_price"])

            # Get 5 trading days after pick_date
            eval_dates = _get_trading_days_after(con, pick_date, EVAL_WINDOW)
            if len(eval_dates) < EVAL_WINDOW:
                # Not enough days yet
                skipped += 1
                continue

            ohlcv = _load_ohlcv(con, ticker, eval_dates)
            if len(ohlcv) < EVAL_WINDOW:
                # Ticker missing from bars on those dates — use what we have
                if ohlcv.empty:
                    skipped += 1
                    continue

            result = evaluate_pick(ticker, direction, entry_price, ohlcv)
            eval_date = eval_dates[-1]

            con.execute(
                """
                UPDATE pick_tracking
                SET outcome = ?, exit_price = ?, exit_date = ?,
                    return_pct = ?, days_held = ?, hit_tp_first = ?,
                    eval_date = ?
                WHERE pick_date = ? AND ticker = ?
                """,
                (
                    result["outcome"],
                    result["exit_price"],
                    result["exit_date"],
                    result["return_pct"],
                    result["days_held"],
                    result["hit_tp_first"],
                    eval_date,
                    pick_date,
                    ticker,
                ),
            )
            evaluated += 1

        con.commit()
        return {"evaluated": evaluated, "skipped": skipped, "latest_bar_date": latest_bar_date}
    finally:
        con.close()


# ── Summary ───────────────────────────────────────────────────────────────────

def build_summary(db_path: Path) -> dict[str, Any]:
    """Return win-rate summary across all evaluated picks."""
    ensure_table(db_path)
    con = _connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT pick_date, ticker, direction, entry_price,
                   tcn_score, factor_rank, final_score,
                   outcome, return_pct, days_held, eval_date
            FROM pick_tracking
            WHERE outcome != 'PENDING'
            ORDER BY pick_date ASC
            """
        ).fetchall()

        pending_count = con.execute(
            "SELECT COUNT(*) FROM pick_tracking WHERE outcome = 'PENDING'"
        ).fetchone()[0]

        if not rows:
            return {
                "total": 0,
                "pending": pending_count,
                "wins": 0,
                "losses": 0,
                "timeouts": 0,
                "win_rate": None,
                "avg_return_pct": None,
                "total_return_pct": None,
                "by_direction": {},
                "by_tcn_bucket": {},
                "pnl_curve": [],
            }

        data = [dict(r) for r in rows]
        df = pd.DataFrame(data)

        total = len(df)
        wins = int((df["outcome"] == "WIN").sum())
        losses = int((df["outcome"] == "LOSE").sum())
        timeouts = int((df["outcome"] == "TIMEOUT").sum())
        win_rate = round(wins / total, 4) if total > 0 else None
        avg_return = round(float(df["return_pct"].mean()) * 100, 4) if total > 0 else None
        total_return = round(float(df["return_pct"].sum()) * 100, 4) if total > 0 else None

        # By direction
        by_direction: dict[str, Any] = {}
        for direction in ["LONG", "SHORT"]:
            sub = df[df["direction"] == direction]
            n = len(sub)
            if n == 0:
                continue
            w = int((sub["outcome"] == "WIN").sum())
            by_direction[direction] = {
                "total": n,
                "wins": w,
                "losses": int((sub["outcome"] == "LOSE").sum()),
                "timeouts": int((sub["outcome"] == "TIMEOUT").sum()),
                "win_rate": round(w / n, 4),
                "avg_return_pct": round(float(sub["return_pct"].mean()) * 100, 4),
            }

        # By TCN bucket (quartiles: 0-25%, 25-50%, 50-75%, 75-100%)
        by_tcn_bucket: dict[str, Any] = {}
        buckets = [
            ("0-25%", 0.0, 0.25),
            ("25-50%", 0.25, 0.50),
            ("50-75%", 0.50, 0.75),
            ("75-100%", 0.75, 1.01),
        ]
        tcn_col = df["tcn_score"].fillna(0.5)
        for label, lo, hi in buckets:
            mask = (tcn_col >= lo) & (tcn_col < hi)
            sub = df[mask]
            n = len(sub)
            if n == 0:
                continue
            w = int((sub["outcome"] == "WIN").sum())
            by_tcn_bucket[label] = {
                "total": n,
                "wins": w,
                "win_rate": round(w / n, 4),
                "avg_return_pct": round(float(sub["return_pct"].mean()) * 100, 4),
            }

        # P&L curve: cumulative return by pick_date
        df_sorted = df.sort_values("pick_date")
        df_sorted["cum_return"] = df_sorted["return_pct"].cumsum()
        pnl_curve = [
            {"date": str(row["pick_date"]), "cum_return_pct": round(float(row["cum_return"]) * 100, 4)}
            for _, row in df_sorted.iterrows()
        ]

        return {
            "total": total,
            "pending": pending_count,
            "wins": wins,
            "losses": losses,
            "timeouts": timeouts,
            "win_rate": win_rate,
            "avg_return_pct": avg_return,
            "total_return_pct": total_return,
            "by_direction": by_direction,
            "by_tcn_bucket": by_tcn_bucket,
            "pnl_curve": pnl_curve,
        }
    finally:
        con.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meridian forward tracker")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--evaluate", action="store_true",
                        help="Evaluate all PENDING picks with 5+ days of data")
    parser.add_argument("--backfill", action="store_true",
                        help="Backfill: re-evaluate picks since --start-date")
    parser.add_argument("--start-date", default=None,
                        help="Start date for --backfill (YYYY-MM-DD)")
    parser.add_argument("--snapshot", action="store_true",
                        help="Insert today's shortlist picks with PENDING outcome")
    parser.add_argument("--snapshot-date", default=None,
                        help="Override pick date for --snapshot (YYYY-MM-DD)")
    parser.add_argument("--summary", action="store_true",
                        help="Print win-rate summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db).expanduser().resolve()
    ensure_table(db_path)

    if args.snapshot:
        n = snapshot_picks(db_path, pick_date=args.snapshot_date)
        print(json.dumps({"ok": True, "inserted": n}))
        return 0

    if args.evaluate:
        result = _evaluate_pending(db_path)
        print(json.dumps({"ok": True, **result}))
        return 0

    if args.backfill:
        if not args.start_date:
            print("Error: --backfill requires --start-date YYYY-MM-DD", file=sys.stderr)
            return 1
        # Reset PENDING flags for picks since start_date so they get re-evaluated
        con = _connect(db_path)
        try:
            con.execute(
                """
                UPDATE pick_tracking
                SET outcome = 'PENDING', exit_price = NULL, exit_date = NULL,
                    return_pct = NULL, days_held = NULL, hit_tp_first = NULL, eval_date = NULL
                WHERE pick_date >= ? AND outcome != 'PENDING'
                """,
                (args.start_date,),
            )
            reset_count = con.execute("SELECT changes()").fetchone()[0]
            con.commit()
        finally:
            con.close()
        result = _evaluate_pending(db_path, since_date=args.start_date)
        print(json.dumps({"ok": True, "reset": reset_count, **result}))
        return 0

    if args.summary:
        summary = build_summary(db_path)
        print(json.dumps(summary, indent=2))
        return 0

    print("No action specified. Use --evaluate, --backfill, --snapshot, or --summary.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
