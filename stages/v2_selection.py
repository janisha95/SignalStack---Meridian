#!/usr/bin/env python3
"""Meridian Stage 5 — Shortlist Selection (dual-TCN algo trader).

Pipeline:
  1. Load predictions_daily  →  tcn_long_score + tcn_short_score per ticker
  2. LONG:  nlargest(top_n, 'tcn_long_score')
  3. SHORT: nlargest(top_n, 'tcn_short_score')
  4. Assign rank 1..N per side, write to shortlist_daily
  Legacy columns (predicted_return, beta, residual_alpha, factor_rank) are
  set to neutral (0.0) for API compatibility downstream.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stages.factors import now_utc_iso, today_et
from stages.v2_prefilter import PrefilterError, run_prefilter


# ── Constants ─────────────────────────────────────────────────────────────────

STAGE_NAME    = "selection"
ROOT          = Path(__file__).resolve().parents[1]
DEFAULT_DB    = ROOT / "data" / "v2_universe.db"
DEFAULT_TOP_N = 30
ETF_LIST_PATH = ROOT / "config" / "etf_tickers.json"

try:
    EXCLUDE_ETFS = set(json.loads(ETF_LIST_PATH.read_text())) if ETF_LIST_PATH.exists() else set()
except Exception:
    EXCLUDE_ETFS = set()


# ── Helpers ───────────────────────────────────────────────────────────────────

class SelectionError(RuntimeError):
    pass


def _log(msg: str) -> None:
    print(f"[{STAGE_NAME}] {msg}", flush=True)


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SelectionError(f"DB not found: {db_path}")
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


# ── Predictions loaders ───────────────────────────────────────────────────────

def _load_prefilter(db_path: Path) -> pd.DataFrame:
    con = _connect(db_path)
    try:
        if _table_exists(con, "prefilter_results"):
            row = con.execute("SELECT MAX(date) AS d FROM prefilter_results").fetchone()
            date = str(row["d"]) if row and row["d"] else None
            if date:
                df = pd.read_sql_query(
                    "SELECT ticker, regime, price, sector FROM prefilter_results"
                    " WHERE date=? ORDER BY ticker ASC",
                    con, params=(date,),
                )
                if not df.empty:
                    df.attrs["date"] = date
                    return df
    finally:
        con.close()
    return run_prefilter(db_path, dry_run=True)


def _mock_predictions(db_path: Path) -> pd.DataFrame:
    """Mock: random TCN-like scores in [0.3, 0.9]."""
    prefilter = _load_prefilter(db_path)
    if prefilter.empty:
        raise SelectionError("Prefilter empty — cannot generate mock predictions")
    rng = np.random.default_rng(42)
    df = prefilter.copy()
    df["tcn_long_score"]  = rng.uniform(0.3, 0.9, len(df)).astype(np.float32)
    df["tcn_short_score"] = rng.uniform(0.3, 0.9, len(df)).astype(np.float32)
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df.attrs["date"] = df.attrs.get("date", today_et())
    return df


def _load_predictions(db_path: Path, *, mock: bool) -> pd.DataFrame:
    if mock:
        return _mock_predictions(db_path)
    con = _connect(db_path)
    try:
        if not _table_exists(con, "predictions_daily"):
            raise SelectionError("predictions_daily missing — use --mock until Stage 4 runs")
        row = con.execute("SELECT MAX(date) AS d FROM predictions_daily").fetchone()
        as_of = str(row["d"]) if row and row["d"] else None
        if not as_of:
            raise SelectionError("predictions_daily is empty")
        df = pd.read_sql_query(
            "SELECT * FROM predictions_daily WHERE date=? ORDER BY ticker ASC",
            con, params=(as_of,),
        )
        df["ticker"] = df["ticker"].astype(str).str.upper()
        return df
    finally:
        con.close()


# ── DB write ──────────────────────────────────────────────────────────────────

def _ensure_table(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS shortlist_daily (
            date             TEXT NOT NULL,
            ticker           TEXT NOT NULL,
            direction        TEXT NOT NULL,
            predicted_return REAL,
            beta             REAL,
            market_component REAL,
            residual_alpha   REAL,
            rank             INTEGER,
            regime           TEXT,
            sector           TEXT,
            price            REAL,
            top_shap_factors TEXT,
            factor_rank      REAL,
            tcn_score        REAL,
            final_score      REAL,
            PRIMARY KEY (date, ticker)
        )
    """)
    existing = {r[1] for r in con.execute("PRAGMA table_info(shortlist_daily)").fetchall()}
    for col, typ in {
        "market_component": "REAL",
        "top_shap_factors": "TEXT",
        "factor_rank":      "REAL",
        "tcn_score":        "REAL",
        "final_score":      "REAL",
    }.items():
        if col not in existing:
            con.execute(f"ALTER TABLE shortlist_daily ADD COLUMN {col} {typ}")
    con.commit()


def _n(val: Any) -> Any:
    """Return None if NaN/inf, else the value."""
    try:
        if pd.isna(val) or (isinstance(val, float) and not np.isfinite(val)):
            return None
    except Exception:
        pass
    return val


def _write_shortlist(con: sqlite3.Connection, frame: pd.DataFrame, run_date: str) -> int:
    _ensure_table(con)
    con.execute("DELETE FROM shortlist_daily WHERE date=?", (run_date,))
    rows = [
        (
            run_date,
            r["ticker"],
            r["direction"],
            _n(r["predicted_return"]),
            _n(r["beta"]),
            _n(r["market_component"]),
            _n(r["residual_alpha"]),
            int(r["rank"]) if _n(r["rank"]) is not None else None,
            r["regime"],
            r["sector"],
            _n(r["price"]),
            r["top_shap_factors"],
            _n(r["factor_rank"]),
            _n(r["tcn_score"]),
            _n(r["final_score"]),
        )
        for _, r in frame.iterrows()
    ]
    con.executemany("""
        INSERT OR REPLACE INTO shortlist_daily (
            date, ticker, direction,
            predicted_return, beta, market_component, residual_alpha,
            rank, regime, sector, price, top_shap_factors,
            factor_rank, tcn_score, final_score
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    con.execute(
        "INSERT OR REPLACE INTO cache_meta (key, value, updated_at) VALUES (?,?,?)",
        ("selection_run_at", now_utc_iso(), now_utc_iso()),
    )
    con.commit()
    return len(rows)


# ── Main selection ────────────────────────────────────────────────────────────

def select_shortlist(
    *,
    db_path: Path,
    top_n: int = DEFAULT_TOP_N,
    min_residual: float = 0.0,   # kept for API compat, unused in dual-TCN mode
    show_all: bool = False,
    dry_run: bool = False,
    debug_ticker: str | None = None,
    mock: bool = False,
) -> pd.DataFrame:
    t0 = time.time()
    _log("Starting Stage 5 (dual-TCN mode)")

    # ── 1. Load predictions ───────────────────────────────────────────────────
    predictions = _load_predictions(db_path, mock=mock)
    if predictions.empty:
        raise SelectionError("Predictions frame is empty")
    predictions["ticker"] = predictions["ticker"].astype(str).str.upper()
    _log(f"Loaded {len(predictions)} tickers")

    run_date = (
        str(predictions["date"].dropna().max())
        if "date" in predictions.columns and not predictions["date"].dropna().empty
        else today_et()
    )
    _log(f"Run date: {run_date}")

    # Ensure score columns exist with neutral fallback
    for col in ("tcn_long_score", "tcn_short_score"):
        if col not in predictions.columns:
            predictions[col] = 0.5
        predictions[col] = predictions[col].fillna(0.5)

    # Exclude SPY from candidate pool
    pool = predictions[predictions["ticker"] != "SPY"].copy()
    if pool.empty:
        raise SelectionError("Candidate pool is empty after excluding SPY")

    n_pick = len(pool) if show_all else top_n

    # ── 2. LONG: top N by tcn_long_score ─────────────────────────────────────
    long_pool = pool[~pool["ticker"].isin(EXCLUDE_ETFS)].copy()
    if long_pool.empty:
        raise SelectionError("LONG pool is empty after ETF exclusion")
    long_picks = long_pool.nlargest(n_pick, "tcn_long_score").copy()
    long_picks["direction"]   = "LONG"
    long_picks["final_score"] = long_picks["tcn_long_score"]
    long_picks["tcn_score"]   = long_picks["tcn_long_score"]
    long_picks["rank"]        = range(1, len(long_picks) + 1)

    # ── 3. SHORT: top N by tcn_short_score ───────────────────────────────────
    short_picks = pool.nlargest(n_pick, "tcn_short_score").copy()
    short_picks["direction"]   = "SHORT"
    short_picks["final_score"] = short_picks["tcn_short_score"]
    short_picks["tcn_score"]   = short_picks["tcn_short_score"]
    short_picks["rank"]        = range(1, len(short_picks) + 1)

    # ── 4. Set legacy columns to neutral ─────────────────────────────────────
    for df in (long_picks, short_picks):
        df["predicted_return"] = 0.0
        df["beta"]             = 0.0
        df["market_component"] = 0.0
        df["residual_alpha"]   = 0.0
        df["factor_rank"]      = 0.0
        df["top_shap_factors"] = None
        for col in ("regime", "sector", "price"):
            if col not in df.columns:
                df[col] = None

    # ── 5. Assemble ───────────────────────────────────────────────────────────
    shortlist = pd.concat([long_picks, short_picks], ignore_index=True)
    shortlist = shortlist[[
        "ticker", "direction", "predicted_return", "beta", "market_component",
        "residual_alpha", "rank", "regime", "sector", "price", "top_shap_factors",
        "factor_rank", "tcn_score", "final_score",
    ]]
    shortlist = shortlist.sort_values(["direction", "rank"]).reset_index(drop=True)

    # ── Progress log ──────────────────────────────────────────────────────────
    def _preview(df: pd.DataFrame) -> str:
        return ", ".join(
            f"{r.ticker}(tcn={r.tcn_score:.3f})"
            for r in df.head(3).itertuples(index=False)
        )
    _log(f"Top 3 LONGs:  {_preview(long_picks)}")
    _log(f"Top 3 SHORTs: {_preview(short_picks)}")
    _log(f"Selected {len(long_picks)} LONG + {len(short_picks)} SHORT")

    # ── Debug ticker ──────────────────────────────────────────────────────────
    if debug_ticker:
        t = debug_ticker.upper()
        hit = pool.loc[pool["ticker"] == t]
        if hit.empty:
            _log(f"[DEBUG] {t} not found in candidate pool")
        else:
            r = hit.iloc[0]
            long_s  = float(r.get("tcn_long_score",  0.5))
            short_s = float(r.get("tcn_short_score", 0.5))
            _log(f"[DEBUG] {t}: tcn_long={long_s:.4f}  tcn_short={short_s:.4f}")
            in_sl = shortlist.loc[shortlist["ticker"] == t]
            if not in_sl.empty:
                sr = in_sl.iloc[0]
                _log(f"  direction={sr['direction']}  rank={sr['rank']}  final={sr['final_score']:.4f}")
            else:
                _log(f"  not in shortlist (top_n={top_n})")

    # ── Write DB ──────────────────────────────────────────────────────────────
    if not dry_run:
        con = _connect(db_path)
        try:
            written = _write_shortlist(con, shortlist, run_date)
        finally:
            con.close()
        _log(f"Written {written} rows for date={run_date}")

    _log(f"DONE in {time.time()-t0:.1f}s")
    return shortlist


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Meridian Stage 5 — Selection (dual-TCN)")
    p.add_argument("--db",      default=str(DEFAULT_DB))
    p.add_argument("--top-n",   type=int, default=DEFAULT_TOP_N)
    p.add_argument("--show-all", action="store_true")
    p.add_argument("--dry-run",  action="store_true")
    p.add_argument("--debug",    default=None)
    p.add_argument("--mock",     action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        frame = select_shortlist(
            db_path=Path(args.db).expanduser().resolve(),
            top_n=args.top_n,
            show_all=args.show_all,
            dry_run=args.dry_run,
            debug_ticker=args.debug,
            mock=args.mock,
        )
    except (SelectionError, PrefilterError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({
        "ok":     True,
        "rows":   len(frame),
        "longs":  int((frame["direction"] == "LONG").sum()),
        "shorts": int((frame["direction"] == "SHORT").sum()),
        "sample": frame.head(5).to_dict(orient="records"),
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Backward compat alias for orchestrator import
generate_mock_predictions = _mock_predictions
