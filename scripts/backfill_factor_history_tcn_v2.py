#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.factors import compute_atr, compute_macd_histogram


DB_PATH = Path("/Users/sjani008/SS/Meridian/data/v2_universe.db")
MISSING_FEATURES = [
    "momentum_impulse",
    "volume_flow_direction",
    "effort_vs_result",
    "volatility_acceleration",
    "wick_rejection",
    "rollover_strength",
    "rs_momentum",
]
BATCH_SIZE = 100
HISTORY_PADDING_DAYS = 200


def _log(msg: str) -> None:
    print(f"[fh_backfill] {msg}", flush=True)


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _rolling_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    mean = values.rolling(window).mean()
    std = values.rolling(window).std(ddof=1)
    z = (values - mean) / std
    z = z.mask(std.isna(), np.nan)
    z = z.mask((std == 0) & mean.notna(), 0.0)
    return z


def _load_metadata(con: sqlite3.Connection) -> tuple[str, list[str], pd.DataFrame]:
    min_date = str(con.execute("SELECT MIN(date) FROM factor_history").fetchone()[0])
    tickers = [
        str(row[0]).upper()
        for row in con.execute("SELECT DISTINCT ticker FROM factor_history ORDER BY ticker ASC").fetchall()
        if row[0]
    ]
    spy_df = pd.read_sql_query(
        """
        SELECT date, close
        FROM daily_bars
        WHERE ticker = 'SPY'
        ORDER BY date ASC
        """,
        con,
    )
    if spy_df.empty:
        raise RuntimeError("SPY daily_bars history missing")
    spy_df["date"] = spy_df["date"].astype(str)
    spy_df["spy_close"] = pd.to_numeric(spy_df["close"], errors="coerce").astype(float)
    return min_date, tickers, spy_df[["date", "spy_close"]]


def _load_batch_daily_bars(
    con: sqlite3.Connection,
    tickers: list[str],
    min_date: str,
) -> pd.DataFrame:
    placeholders = ",".join("?" * len(tickers))
    params = [*tickers, min_date]
    return pd.read_sql_query(
        f"""
        SELECT ticker, date, open, high, low, close, volume
        FROM daily_bars
        WHERE ticker IN ({placeholders})
          AND date >= date(?, '-{HISTORY_PADDING_DAYS} days')
        ORDER BY ticker ASC, date ASC
        """,
        con,
        params=params,
    )


def _load_batch_factor_history_keys(
    con: sqlite3.Connection,
    tickers: list[str],
    min_date: str,
) -> pd.DataFrame:
    placeholders = ",".join("?" * len(tickers))
    params = [*tickers, min_date]
    return pd.read_sql_query(
        f"""
        SELECT date, ticker
        FROM factor_history
        WHERE ticker IN ({placeholders})
          AND date >= ?
        ORDER BY ticker ASC, date ASC
        """,
        con,
        params=params,
    )


def _compute_batch_features(frame: pd.DataFrame, spy_df: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "ticker", *MISSING_FEATURES])

    frame = frame.copy()
    frame["date"] = frame["date"].astype(str)
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").astype(float)
    frame = frame.merge(spy_df, on="date", how="left")

    outputs: list[pd.DataFrame] = []
    for ticker, grp in frame.groupby("ticker", sort=False):
        grp = grp.sort_values("date").reset_index(drop=True)
        close = grp["close"]
        high = grp["high"]
        low = grp["low"]
        open_ = grp["open"]
        volume = grp["volume"].fillna(0.0)

        atr = compute_atr(grp[["high", "low", "close"]], 14)
        macd_hist = compute_macd_histogram(close)
        vol_ma20 = volume.rolling(20).mean()
        obv = (np.sign(close.diff().fillna(0.0)) * volume).cumsum()
        evr_raw = (high - low) / volume.replace(0, np.nan)
        wick_range = (high - low).replace(0, np.nan)
        wick_raw = ((high - close) - (close - low)) / wick_range
        atr_pct = atr / close.replace(0, np.nan)

        rs_10 = (close / close.shift(10) - 1.0) - (grp["spy_close"] / grp["spy_close"].shift(10) - 1.0)
        rs_20 = (close / close.shift(20) - 1.0) - (grp["spy_close"] / grp["spy_close"].shift(20) - 1.0)

        out = pd.DataFrame(
            {
                "date": grp["date"],
                "ticker": ticker,
                "momentum_impulse": _rolling_zscore(macd_hist / atr.replace(0, np.nan), 20),
                "volume_flow_direction": _rolling_zscore(obv.diff(5) / (vol_ma20 * 5).replace(0, np.nan), 20),
                "effort_vs_result": _rolling_zscore(evr_raw, 20),
                "volatility_acceleration": _rolling_zscore(atr_pct.pct_change(5), 20),
                "wick_rejection": _rolling_zscore(wick_raw, 20),
                "rollover_strength": (open_ - close) / atr.replace(0, np.nan),
                "rs_momentum": rs_10 - rs_20,
            }
        )
        outputs.append(out)

    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame(columns=["date", "ticker", *MISSING_FEATURES])


def _update_factor_history(con: sqlite3.Connection, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    rows = []
    for row in frame.itertuples(index=False):
        rows.append(
            tuple(None if pd.isna(getattr(row, feature)) else float(getattr(row, feature)) for feature in MISSING_FEATURES)
            + (row.date, row.ticker)
        )
    con.executemany(
        """
        UPDATE factor_history
        SET momentum_impulse = ?,
            volume_flow_direction = ?,
            effort_vs_result = ?,
            volatility_acceleration = ?,
            wick_rejection = ?,
            rollover_strength = ?,
            rs_momentum = ?
        WHERE date = ? AND ticker = ?
        """,
        rows,
    )
    return con.total_changes


def main() -> int:
    start = time.time()
    con = _connect()
    try:
        min_date, tickers, spy_df = _load_metadata(con)
        _log(f"factor_history start date: {min_date}")
        _log(f"tickers to process: {len(tickers)}")
        _log(f"spy history rows: {len(spy_df)}")

        total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        total_updates = 0
        for batch_idx, offset in enumerate(range(0, len(tickers), BATCH_SIZE), start=1):
            batch = tickers[offset : offset + BATCH_SIZE]
            daily_df = _load_batch_daily_bars(con, batch, min_date)
            keys_df = _load_batch_factor_history_keys(con, batch, min_date)
            feature_df = _compute_batch_features(daily_df, spy_df)
            if not keys_df.empty:
                feature_df = keys_df.merge(feature_df, on=["date", "ticker"], how="left")
            before = con.total_changes
            updated = _update_factor_history(con, feature_df)
            batch_updates = updated - before
            total_updates += batch_updates
            con.commit()
            _log(
                f"batch {batch_idx}/{total_batches}: "
                f"{len(batch)} tickers, {len(keys_df)} target rows, {batch_updates} updates"
            )

        _log(f"done in {time.time() - start:.1f}s | total_updates={total_updates}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
