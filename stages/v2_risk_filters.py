#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stages.factors import compute_atr, now_et, now_et_iso, now_utc_iso, today_et
from stages.v2_selection import SelectionError, select_shortlist


STAGE_NAME = "risk"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "v2_universe.db"
RISK_CONFIG_PATH = ROOT / "config" / "risk_config.json"
DEFAULT_PROP_FIRM = "trade_the_pool_day_50k"
KNOWN_LEVERAGED = {
    "TQQQ", "SQQQ", "SPXL", "SPXS", "UVXY", "SVXY",
    "LABU", "LABD", "NUGT", "DUST", "JNUG", "JDST",
    "FAS", "FAZ", "TNA", "TZA", "TECL", "TECS",
    "SOXL", "SOXS", "UDOW", "SDOW", "UPRO", "SDS",
    "QLD", "QID", "DDM", "DXD", "MVV", "MZZ",
    "TWM", "UWM", "BTCZ", "SBIT", "TSLQ", "MSTZ",
    "AMDD", "TSDD", "UVIX", "GDXU", "GDXD",
}


class RiskFilterError(RuntimeError):
    pass


def _progress(message: str) -> None:
    print(f"[{STAGE_NAME}] {message}", flush=True)


def _connect_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise RiskFilterError(f"v2_universe.db missing at {db_path}")
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _latest_table_date(con: sqlite3.Connection, table: str) -> str | None:
    if not _table_exists(con, table):
        return None
    row = con.execute(f"SELECT MAX(date) AS d FROM {table}").fetchone()
    return str(row["d"]) if row and row["d"] is not None else None


def _csv_upper(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip().upper() for part in value.split(",") if part.strip()]


def load_risk_config(
    *,
    prop_firm: str = DEFAULT_PROP_FIRM,
    account_balance: float | None = None,
    risk_per_trade: float | None = None,
    max_positions: int | None = None,
) -> dict[str, Any]:
    if not RISK_CONFIG_PATH.exists():
        raise RiskFilterError(f"risk_config.json missing at {RISK_CONFIG_PATH}")
    raw = json.loads(RISK_CONFIG_PATH.read_text(encoding="utf-8"))
    defaults = dict(raw.get("defaults", {}))
    presets = dict(raw.get("presets", {}))
    if prop_firm not in presets:
        raise RiskFilterError(f"Unknown prop firm preset: {prop_firm}")
    config = {**defaults, **presets.get(prop_firm, {})}
    if account_balance is not None:
        config["account_balance"] = float(account_balance)
    if risk_per_trade is not None:
        config["risk_per_trade_pct"] = float(risk_per_trade)
    if max_positions is not None:
        config["max_positions"] = int(max_positions)
    config["prop_firm"] = prop_firm
    return config


def is_leveraged_inverse(ticker: str) -> bool:
    return str(ticker or "").upper() in KNOWN_LEVERAGED


def check_eod_close(config: dict[str, Any], current_time_et) -> dict[str, bool]:
    if not config.get("must_close_eod", False):
        return {"can_open": True, "must_close": False}
    no_new_after = str(config.get("no_new_trades_after", "15:00"))
    close_by = str(config.get("eod_close_time", "15:30"))
    hour_no_new, min_no_new = [int(part) for part in no_new_after.split(":", 1)]
    hour_close, min_close = [int(part) for part in close_by.split(":", 1)]
    current_hour = current_time_et.hour
    current_min = current_time_et.minute
    can_open = (current_hour < hour_no_new) or (
        current_hour == hour_no_new and current_min < min_no_new
    )
    must_close = (current_hour > hour_close) or (
        current_hour == hour_close and current_min >= min_close
    )
    return {"can_open": can_open, "must_close": must_close}


def check_earnings_today(ticker: str, as_of: str | date) -> bool:
    if yf is None:
        return False
    target_date = str(as_of)
    try:  # pragma: no cover - live network path
        calendar = yf.Ticker(str(ticker).upper()).calendar
        if calendar is None:
            return False
        if hasattr(calendar, "index") and "Earnings Date" in getattr(calendar, "index", []):
            values = calendar.loc["Earnings Date"]
        elif isinstance(calendar, dict) and "Earnings Date" in calendar:
            values = calendar["Earnings Date"]
        else:
            values = calendar
        if not isinstance(values, (list, tuple, pd.Series, pd.Index, np.ndarray)):
            values = [values]
        for item in values:
            try:
                parsed = pd.Timestamp(item)
            except Exception:
                continue
            if parsed.strftime("%Y-%m-%d") == target_date:
                return True
    except Exception:
        return False
    return False


def _ensure_risk_tables(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS tradeable_portfolio (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            shares INTEGER,
            entry_price REAL,
            stop_price REAL,
            tp_price REAL,
            risk_dollars REAL,
            risk_pct REAL,
            position_value REAL,
            atr REAL,
            sector TEXT,
            regime TEXT,
            rank INTEGER,
            predicted_return REAL,
            beta REAL,
            residual_alpha REAL,
            filter_status TEXT,
            filter_reason TEXT,
            PRIMARY KEY (date, ticker, direction)
        );

        CREATE TABLE IF NOT EXISTS portfolio_state (
            date TEXT NOT NULL,
            account_balance REAL,
            daily_pnl REAL,
            total_pnl REAL,
            total_pnl_pct REAL,
            max_drawdown REAL,
            max_drawdown_pct REAL,
            open_positions INTEGER,
            portfolio_heat_pct REAL,
            daily_loss_remaining REAL,
            drawdown_remaining REAL,
            distance_to_target REAL,
            best_day_pnl REAL,
            best_day_pct_of_total REAL,
            trading_days INTEGER,
            PRIMARY KEY (date)
        );

        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            direction TEXT,
            entry_date TEXT,
            entry_price REAL,
            shares INTEGER,
            exit_date TEXT,
            exit_price REAL,
            exit_reason TEXT,
            pnl_dollars REAL,
            pnl_pct REAL,
            hold_days INTEGER,
            risk_dollars REAL
        );
        """
    )

    cols = {
        str(row[1])
        for row in con.execute("PRAGMA table_info(tradeable_portfolio)").fetchall()
    }
    wanted = {
        "regime": "TEXT",
        "predicted_return": "REAL",
        "beta": "REAL",
        "filter_reason": "TEXT",
    }
    for name, col_type in wanted.items():
        if name not in cols:
            con.execute(f"ALTER TABLE tradeable_portfolio ADD COLUMN {name} {col_type}")
    con.commit()


def _load_portfolio_state(con: sqlite3.Connection, config: dict[str, Any]) -> dict[str, Any]:
    _ensure_risk_tables(con)
    row = con.execute("SELECT * FROM portfolio_state ORDER BY date DESC LIMIT 1").fetchone()
    if not row:
        balance = float(config["account_balance"])
        return {
            "account_balance": balance,
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "open_positions": 0,
            "portfolio_heat_pct": 0.0,
            "daily_loss_remaining": float(config["max_daily_loss_pct"]) * balance,
            "drawdown_remaining": float(config["max_total_drawdown_pct"]) * balance,
            "distance_to_target": float(config["profit_target_pct"]) * balance,
            "best_day_pnl": 0.0,
            "best_day_pct_of_total": 0.0,
            "trading_days": 0,
        }
    return dict(row)


def _best_day_metrics(con: sqlite3.Connection) -> tuple[float, float, int]:
    rows = con.execute(
        """
        SELECT exit_date, SUM(COALESCE(pnl_dollars, 0)) AS pnl
        FROM trade_log
        WHERE exit_date IS NOT NULL
        GROUP BY exit_date
        ORDER BY exit_date ASC
        """
    ).fetchall()
    if not rows:
        return 0.0, 0.0, 0
    pnls = [float(row["pnl"] or 0.0) for row in rows]
    best_day = max(pnls)
    total = sum(pnls)
    best_pct = (best_day / total) if total > 0 else 0.0
    return best_day, best_pct, len(rows)


def _load_shortlist(db_path: Path, *, mock: bool, show_all: bool = False) -> pd.DataFrame:
    if mock:
        return select_shortlist(db_path=db_path, dry_run=True, mock=True, show_all=show_all)
    con = _connect_db(db_path)
    try:
        if not _table_exists(con, "shortlist_daily"):
            raise RiskFilterError("shortlist_daily missing; use --mock or run Stage 5 first")
        run_date = _latest_table_date(con, "shortlist_daily")
        if not run_date:
            raise RiskFilterError("shortlist_daily is empty")
        cols = {
            row["name"] for row in con.execute("PRAGMA table_info(shortlist_daily)").fetchall()
        }
        top_shap = "top_shap_factors" if "top_shap_factors" in cols else "NULL AS top_shap_factors"
        market_component = "market_component" if "market_component" in cols else "NULL AS market_component"
        frame = pd.read_sql_query(
            f"""
            SELECT ticker, direction, predicted_return, beta, {market_component},
                   residual_alpha, rank, regime, sector, price, {top_shap}
            FROM shortlist_daily
            WHERE date = ?
            ORDER BY direction ASC, rank ASC, ticker ASC
            """,
            con,
            params=(run_date,),
        )
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        return frame
    finally:
        con.close()


def _load_prefilter_lookup(con: sqlite3.Connection) -> pd.DataFrame:
    run_date = _latest_table_date(con, "prefilter_results")
    if not run_date:
        return pd.DataFrame(columns=["ticker", "regime", "sector", "price", "atr_pct", "adx"])
    frame = pd.read_sql_query(
        """
        SELECT ticker, regime, sector, price, atr_pct, adx
        FROM prefilter_results
        WHERE date = ?
        ORDER BY ticker ASC
        """,
        con,
        params=(run_date,),
    )
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    return frame


def _load_price_history(db_path: Path, tickers: list[str], bars: int = 120) -> dict[str, pd.DataFrame]:
    if not tickers:
        return {}
    con = _connect_db(db_path)
    try:
        chunk_size = 900
        frames: list[pd.DataFrame] = []
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            sql = f"""
                WITH ranked AS (
                    SELECT
                        ticker,
                        date,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
                    FROM daily_bars
                    WHERE ticker IN ({placeholders})
                )
                SELECT ticker, date, open, high, low, close, volume
                FROM ranked
                WHERE rn <= ?
                ORDER BY ticker ASC, date ASC
            """
            frames.append(pd.read_sql_query(sql, con, params=[*chunk, bars]))
    finally:
        con.close()
    full = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out: dict[str, pd.DataFrame] = {}
    for ticker, frame in full.groupby("ticker", sort=False):
        df = frame.reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        out[str(ticker).upper()] = df
    return out


def compute_position(
    ticker: str,
    direction: str,
    price: float,
    atr: float,
    config: dict[str, Any],
    portfolio_state: dict[str, Any],
) -> dict[str, Any] | None:
    account_balance = float(config["account_balance"])
    risk_per_trade = float(config["risk_per_trade_pct"]) * account_balance
    max_risk = float(config["max_risk_per_trade_pct"]) * account_balance
    daily_remaining = float(portfolio_state["daily_loss_remaining"])
    risk_dollars = min(risk_per_trade, max_risk, daily_remaining)
    if risk_dollars <= 0 or atr <= 0 or price <= 0:
        return None
    stop_distance = atr * float(config["stop_atr_multiple"])
    if stop_distance <= 0:
        return None
    shares = int(risk_dollars / stop_distance)
    if shares <= 0:
        return None
    if direction.upper() == "LONG":
        stop_price = price - stop_distance
        tp_price = price + (atr * float(config["tp_atr_multiple"]))
    else:
        stop_price = price + stop_distance
        tp_price = price - (atr * float(config["tp_atr_multiple"]))
    return {
        "shares": shares,
        "entry_price": round(price, 2),
        "stop_price": round(stop_price, 2),
        "tp_price": round(tp_price, 2),
        "risk_dollars": round(risk_dollars, 2),
        "risk_pct": round((risk_dollars / account_balance) * 100.0, 3),
        "position_value": round(shares * price, 2),
        "atr": round(atr, 4),
        "stop_distance": round(stop_distance, 4),
    }


def check_correlation(
    ticker: str,
    existing_positions: list[str],
    ohlcv_dict: dict[str, pd.DataFrame],
    threshold: float = 0.85,
) -> tuple[bool, str | None, float | None]:
    ticker_df = ohlcv_dict.get(ticker)
    if ticker_df is None or ticker_df.empty:
        return True, None, None
    ticker_returns = ticker_df["close"].pct_change().tail(60)
    for existing in existing_positions:
        other = ohlcv_dict.get(existing)
        if other is None or other.empty:
            continue
        corr = float(ticker_returns.corr(other["close"].pct_change().tail(60)))
        if not np.isnan(corr) and abs(corr) > threshold:
            return False, existing, corr
    return True, None, None


def _load_open_positions(
    con: sqlite3.Connection,
    sector_lookup: dict[str, str],
) -> list[dict[str, Any]]:
    _ensure_risk_tables(con)
    rows = con.execute(
        """
        SELECT ticker, direction, shares, risk_dollars
        FROM trade_log
        WHERE exit_date IS NULL
        ORDER BY entry_date ASC, id ASC
        """
    ).fetchall()
    return [
        {
            "ticker": str(row["ticker"]).upper(),
            "direction": str(row["direction"] or "LONG").upper(),
            "shares": int(row["shares"] or 0),
            "risk_dollars": float(row["risk_dollars"] or 0.0),
            "sector": sector_lookup.get(str(row["ticker"]).upper(), ""),
        }
        for row in rows
    ]


def _build_manual_candidates(
    *,
    db_path: Path,
    tickers: list[str],
    directions: list[str],
    mock: bool,
) -> pd.DataFrame:
    if not tickers:
        raise RiskFilterError("Manual candidate list is empty")
    try:
        shortlist = _load_shortlist(db_path, mock=mock, show_all=True)
        shortlist = shortlist.copy()
        shortlist["ticker"] = shortlist["ticker"].astype(str).str.upper()
        shortlist_idx = shortlist.drop_duplicates(subset=["ticker"], keep="first").set_index("ticker")
    except RiskFilterError:
        shortlist_idx = pd.DataFrame()

    con = _connect_db(db_path)
    try:
        prefilter = _load_prefilter_lookup(con)
    finally:
        con.close()
    prefilter_idx = prefilter.drop_duplicates(subset=["ticker"], keep="first").set_index("ticker") if not prefilter.empty else pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for i, ticker in enumerate(tickers):
        direction = directions[i] if i < len(directions) else "LONG"
        base: dict[str, Any]
        if ticker in shortlist_idx.index:
            base = shortlist_idx.loc[ticker].to_dict()
        elif not prefilter_idx.empty and ticker in prefilter_idx.index:
            base = prefilter_idx.loc[ticker].to_dict()
        else:
            raise RiskFilterError(f"Ticker {ticker} not found in shortlist or prefilter cache")
        rows.append(
            {
                "ticker": ticker,
                "direction": direction,
                "predicted_return": float(base.get("predicted_return")) if pd.notna(base.get("predicted_return")) else float("nan"),
                "beta": float(base.get("beta")) if pd.notna(base.get("beta")) else float("nan"),
                "market_component": float(base.get("market_component")) if pd.notna(base.get("market_component")) else float("nan"),
                "residual_alpha": float(base.get("residual_alpha")) if pd.notna(base.get("residual_alpha")) else float("nan"),
                "rank": int(base.get("rank")) if pd.notna(base.get("rank")) else None,
                "regime": base.get("regime"),
                "sector": base.get("sector"),
                "price": float(base.get("price")) if pd.notna(base.get("price")) else float("nan"),
                "top_shap_factors": base.get("top_shap_factors"),
            }
        )
    return pd.DataFrame(rows)


def _format_short_status(row: pd.Series) -> str:
    if row["filter_status"] == "APPROVED":
        return (
            f"APPROVED ({row['risk_pct']}% risk, {row['sector'] or 'Unknown'} "
            f"{row['sector_count']}/{row['sector_limit']})"
        )
    return f"REJECTED ({row['filter_reason']})"


def _evaluate_candidate(
    row: pd.Series,
    *,
    history: dict[str, pd.DataFrame],
    open_positions: list[dict[str, Any]],
    config: dict[str, Any],
    portfolio_state: dict[str, Any],
) -> dict[str, Any]:
    ticker = str(row["ticker"]).upper()
    direction = str(row["direction"]).upper()
    sector_raw = row.get("sector")
    sector = str(sector_raw).strip() if pd.notna(sector_raw) else ""
    if sector.lower() == "nan":
        sector = ""
    regime = row.get("regime") if pd.notna(row.get("regime")) else None
    price = float(row["price"]) if pd.notna(row.get("price")) else float("nan")

    open_tickers = [pos["ticker"] for pos in open_positions]
    sector_count = sum(1 for pos in open_positions if pos.get("sector") == sector and sector)
    long_count = sum(1 for pos in open_positions if pos["direction"] == "LONG")
    short_count = sum(1 for pos in open_positions if pos["direction"] == "SHORT")
    current_heat_pct = float(portfolio_state.get("portfolio_heat_pct", 0.0))
    current_time_et = now_et()
    eod_state = check_eod_close(config, current_time_et)
    run_date = today_et()

    status = "APPROVED"
    reason = ""
    detail = ""
    atr = float("nan")
    position = None

    if float(portfolio_state.get("drawdown_remaining", 0.0)) <= 0:
        status, reason, detail = "REJECTED", "DRAWDOWN_LIMIT", "Total drawdown limit exhausted"
    elif float(portfolio_state.get("daily_loss_remaining", 0.0)) <= 0:
        status, reason, detail = "REJECTED", "DAILY_LOSS_LIMIT", "Daily loss budget exhausted"
    elif len(open_positions) >= int(config["max_positions"]):
        status, reason, detail = "REJECTED", "MAX_POSITIONS", "Maximum open positions already reached"

    df = history.get(ticker)
    if status == "APPROVED":
        if df is None or len(df) < 20:
            status, reason, detail = "REJECTED", "MISSING_DATA", "Insufficient OHLCV for ATR"
        else:
            avg_volume = float(pd.to_numeric(df["volume"], errors="coerce").tail(20).mean() or 0.0)
            if (
                config.get("block_low_volume") is not None
                and avg_volume < float(config["block_low_volume"])
            ):
                status, reason, detail = "REJECTED", "LOW_VOLUME", "Average daily volume below threshold"
            if status == "APPROVED":
                recent_rets = pd.to_numeric(df["close"], errors="coerce").pct_change().tail(4)
                if recent_rets.notna().any():
                    move_4 = float(recent_rets.add(1.0).prod() - 1.0)
                    if abs(move_4) >= float(config.get("block_high_volatility_4min", 9e9)):
                        status, reason, detail = "REJECTED", "HIGH_VOLATILITY", "Recent move exceeds intraday volatility cap"
            if status == "APPROVED":
                atr_series = compute_atr(df.tail(120).copy(), 14)
                atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else float("nan")
                if np.isnan(atr) or atr <= 0:
                    status, reason, detail = "REJECTED", "MISSING_DATA", "ATR unavailable"

    if status == "APPROVED":
        position = compute_position(ticker, direction, price, atr, config, portfolio_state)
        if position is None:
            status, reason, detail = "REJECTED", "BUDGET_EXHAUSTED", "No remaining risk budget"

    if status == "APPROVED" and config.get("must_close_eod") and not eod_state["can_open"]:
        status, reason, detail = "REJECTED", "EOD_ENTRY_CUTOFF", "No new trades allowed after cutoff"

    if status == "APPROVED" and config.get("block_leveraged_inverse", False) and is_leveraged_inverse(ticker):
        status, reason, detail = "REJECTED", "LEVERAGED_INVERSE", "Leveraged or inverse ETF blocked"

    if status == "APPROVED" and config.get("block_earnings_same_day", False) and check_earnings_today(ticker, run_date):
        status, reason, detail = "REJECTED", "EARNINGS_TODAY", "Ticker reports earnings today"

    if status == "APPROVED" and sector and sector_count >= int(config["max_per_sector"]):
        status, reason, detail = "REJECTED", "SECTOR_CAP", f"{sector} already {sector_count}/{int(config['max_per_sector'])}"

    corr_ticker = None
    corr_value = None
    if status == "APPROVED":
        ok, corr_ticker, corr_value = check_correlation(
            ticker,
            open_tickers,
            history,
            float(config["max_correlation"]),
        )
        if not ok:
            status, reason, detail = "REJECTED", "CORRELATION", f"{corr_value:.2f} corr with {corr_ticker}"

    next_heat_pct = current_heat_pct
    if status == "APPROVED" and position is not None:
        next_heat_pct = current_heat_pct + position["risk_pct"]
        if (next_heat_pct / 100.0) > float(config["max_portfolio_heat_pct"]):
            status, reason, detail = "REJECTED", "HEAT_LIMIT", f"Heat would rise to {next_heat_pct:.2f}%"

    if status == "APPROVED" and position is not None:
        long_after = long_count + (1 if direction == "LONG" else 0)
        short_after = short_count + (1 if direction == "SHORT" else 0)
        total_after = long_after + short_after
        if total_after >= 3 and min(long_after, short_after) > 0:
            imbalance = max(long_after, short_after) / total_after
            if imbalance > float(config["max_direction_imbalance"]):
                status, reason, detail = "REJECTED", "DIRECTION_IMBALANCE", f"Direction imbalance would reach {imbalance:.2f}"

    if status != "APPROVED":
        position = position or {
            "shares": 0,
            "entry_price": round(price, 2) if not np.isnan(price) else None,
            "stop_price": None,
            "tp_price": None,
            "risk_dollars": None,
            "risk_pct": None,
            "position_value": None,
            "atr": round(atr, 4) if not np.isnan(atr) else None,
            "stop_distance": None,
        }

    return {
        "ticker": ticker,
        "direction": direction,
        "shares": position["shares"] if position else 0,
        "entry_price": position["entry_price"] if position else None,
        "stop_price": position["stop_price"] if position else None,
        "tp_price": position["tp_price"] if position else None,
        "risk_dollars": position["risk_dollars"] if position else None,
        "risk_pct": position["risk_pct"] if position else None,
        "position_value": position["position_value"] if position else None,
        "atr": position["atr"] if position else None,
        "sector": sector or None,
        "regime": regime,
        "rank": int(row["rank"]) if pd.notna(row.get("rank")) else None,
        "predicted_return": float(row["predicted_return"]) if pd.notna(row.get("predicted_return")) else None,
        "beta": float(row["beta"]) if pd.notna(row.get("beta")) else None,
        "residual_alpha": float(row["residual_alpha"]) if pd.notna(row.get("residual_alpha")) else None,
        "filter_status": status,
        "filter_reason": "APPROVED" if status == "APPROVED" else reason,
        "detail": detail if status != "APPROVED" else "APPROVED",
        "sector_count": sector_count,
        "sector_limit": int(config["max_per_sector"]),
        "current_heat_pct": round(current_heat_pct, 3),
        "next_heat_pct": round(next_heat_pct, 3),
        "corr_ticker": corr_ticker,
        "corr_value": round(float(corr_value), 4) if corr_value is not None and not np.isnan(corr_value) else None,
        "must_close_eod": bool(eod_state["must_close"]),
    }


def _log_detailed_check(row: dict[str, Any], portfolio_state: dict[str, Any]) -> None:
    ticker = row["ticker"]
    direction = row["direction"]
    _progress(f"Checking {ticker} {direction}...")
    if row["risk_dollars"] is not None:
        _progress(
            f"  Position: {row['shares']} shares @ ${row['entry_price']}, stop ${row['stop_price']}, "
            f"risk ${row['risk_dollars']} ({row['risk_pct']}%)"
        )
    daily_budget = float(portfolio_state.get("daily_loss_remaining", 0.0))
    daily_ok = row["filter_reason"] not in {"DAILY_LOSS_LIMIT", "BUDGET_EXHAUSTED"}
    _progress(
        f"  Daily budget: ${daily_budget:,.0f} remaining {'✓' if daily_ok else 'x'}"
    )
    sector = row["sector"] or "Unknown"
    sector_ok = row["filter_reason"] != "SECTOR_CAP"
    _progress(
        f"  Sector {sector}: {row['sector_count']}/{row['sector_limit']} {'✓' if sector_ok else 'x'}"
    )
    corr_ok = row["filter_reason"] != "CORRELATION"
    if corr_ok:
        _progress("  Correlation: no conflicts ✓")
    else:
        _progress(f"  Correlation: blocked by {row['corr_ticker']} ({row['corr_value']}) x")
    if row["risk_pct"] is not None:
        heat_ok = row["filter_reason"] != "HEAT_LIMIT"
        _progress(
            f"  Portfolio heat: {row['current_heat_pct']}% + {row['risk_pct']}% = "
            f"{row['next_heat_pct']}% {'✓' if heat_ok else 'x'}"
        )
    _progress(f"  {row['filter_status']}{'' if row['filter_status'] == 'APPROVED' else f' ({row['filter_reason']})'}")


def build_tradeable_portfolio(
    *,
    db_path: Path,
    prop_firm: str = DEFAULT_PROP_FIRM,
    account_balance: float | None = None,
    risk_per_trade: float | None = None,
    max_positions: int | None = None,
    dry_run: bool = False,
    debug_ticker: str | None = None,
    mock: bool = False,
    tickers: list[str] | None = None,
    directions: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    t0 = time.time()
    current_time_et = now_et()
    config = load_risk_config(
        prop_firm=prop_firm,
        account_balance=account_balance,
        risk_per_trade=risk_per_trade,
        max_positions=max_positions,
    )
    eod_state = check_eod_close(config, current_time_et)
    con = _connect_db(db_path)
    try:
        portfolio_state = _load_portfolio_state(con, config)
        best_day_pnl, best_day_pct, trading_days = _best_day_metrics(con)
        prefilter = _load_prefilter_lookup(con)
        sector_lookup = {
            str(row["ticker"]).upper(): str(row["sector"] or "")
            for _, row in prefilter.iterrows()
        }
        open_positions = _load_open_positions(con, sector_lookup)
    finally:
        con.close()

    if tickers:
        directions = directions or ["LONG"] * len(tickers)
        if len(directions) not in {1, len(tickers)}:
            raise RiskFilterError("--directions must have length 1 or match --tickers")
        if len(directions) == 1 and len(tickers) > 1:
            directions = directions * len(tickers)
        candidates = _build_manual_candidates(
            db_path=db_path,
            tickers=tickers,
            directions=directions,
            mock=mock,
        )
        detail_mode = True
    else:
        candidates = _load_shortlist(db_path, mock=mock, show_all=False)
        detail_mode = False

    if candidates.empty:
        raise RiskFilterError("Candidate set empty")

    candidates = candidates.copy()
    candidates["ticker"] = candidates["ticker"].astype(str).str.upper()
    tickers_needed = sorted(set(candidates["ticker"].tolist()) | {p["ticker"] for p in open_positions})
    history = _load_price_history(db_path, tickers_needed)

    if tickers:
        _progress(f"Checking {len(candidates)} manual ticker selections against {prop_firm.upper()} rules...")
    else:
        _progress(
            f"Checking {int((candidates['direction'] == 'LONG').sum())} LONG + "
            f"{int((candidates['direction'] == 'SHORT').sum())} SHORT candidates against {prop_firm.upper()} rules..."
        )

    rows: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        out = _evaluate_candidate(
            row,
            history=history,
            open_positions=open_positions,
            config=config,
            portfolio_state=portfolio_state,
        )
        rows.append(out)
        if detail_mode or (debug_ticker and out["ticker"] == debug_ticker.upper()):
            _log_detailed_check(out, portfolio_state)
        else:
            _progress(f"  {out['ticker']} {out['direction']}: {_format_short_status(pd.Series(out))}")

    portfolio = pd.DataFrame(rows).sort_values(["direction", "rank", "ticker"], na_position="last").reset_index(drop=True)
    approved_count = int((portfolio["filter_status"] == "APPROVED").sum())
    rejected_count = len(portfolio) - approved_count

    best_day_warning = (
        best_day_pct >= float(config["best_day_warning_pct"])
        if config.get("best_day_warning_pct") is not None
        else False
    )
    state = {
        "date": today_et(),
        "account_balance": float(config["account_balance"]),
        "daily_pnl": float(portfolio_state.get("daily_pnl", 0.0)),
        "total_pnl": float(portfolio_state.get("total_pnl", 0.0)),
        "total_pnl_pct": float(portfolio_state.get("total_pnl_pct", 0.0)),
        "max_drawdown": float(portfolio_state.get("max_drawdown", 0.0)),
        "max_drawdown_pct": float(portfolio_state.get("max_drawdown_pct", 0.0)),
        "open_positions": int(len(open_positions)),
        "portfolio_heat_pct": float(portfolio_state.get("portfolio_heat_pct", 0.0)),
        "daily_loss_remaining": round(float(portfolio_state.get("daily_loss_remaining", 0.0)), 2),
        "drawdown_remaining": round(float(portfolio_state.get("drawdown_remaining", 0.0)), 2),
        "distance_to_target": round(float(portfolio_state.get("distance_to_target", 0.0)), 2),
        "best_day_pnl": round(best_day_pnl, 2),
        "best_day_pct_of_total": round(best_day_pct, 4),
        "trading_days": int(trading_days),
        "best_day_warning": bool(best_day_warning),
        "must_close_eod": bool(eod_state["must_close"]),
        "can_open_new_trades": bool(eod_state["can_open"]),
    }

    _progress(f"Summary: {approved_count} APPROVED, {rejected_count} REJECTED")
    if best_day_warning:
        _progress(
            f"Warning: best day is {state['best_day_pct_of_total'] * 100:.1f}% of total profit"
        )

    if not dry_run:
        con = _connect_db(db_path)
        try:
            _ensure_risk_tables(con)
            run_date = today_et()
            con.execute("DELETE FROM tradeable_portfolio WHERE date = ?", (run_date,))
            rows_to_write = [
                (
                    run_date,
                    row["ticker"],
                    row["direction"],
                    row["shares"],
                    row["entry_price"],
                    row["stop_price"],
                    row["tp_price"],
                    row["risk_dollars"],
                    row["risk_pct"],
                    row["position_value"],
                    row["atr"],
                    row["sector"],
                    row["regime"],
                    row["rank"],
                    row["predicted_return"],
                    row["beta"],
                    row["residual_alpha"],
                    row["filter_status"],
                    row["filter_reason"],
                )
                for _, row in portfolio.iterrows()
            ]
            con.executemany(
                """
                INSERT OR REPLACE INTO tradeable_portfolio (
                    date, ticker, direction, shares, entry_price, stop_price, tp_price,
                    risk_dollars, risk_pct, position_value, atr, sector, regime, rank,
                    predicted_return, beta, residual_alpha, filter_status, filter_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows_to_write,
            )
            con.execute(
                """
                INSERT OR REPLACE INTO portfolio_state (
                    date, account_balance, daily_pnl, total_pnl, total_pnl_pct,
                    max_drawdown, max_drawdown_pct, open_positions, portfolio_heat_pct,
                    daily_loss_remaining, drawdown_remaining, distance_to_target,
                    best_day_pnl, best_day_pct_of_total, trading_days
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state["date"],
                    state["account_balance"],
                    state["daily_pnl"],
                    state["total_pnl"],
                    state["total_pnl_pct"],
                    state["max_drawdown"],
                    state["max_drawdown_pct"],
                    state["open_positions"],
                    state["portfolio_heat_pct"],
                    state["daily_loss_remaining"],
                    state["drawdown_remaining"],
                    state["distance_to_target"],
                    state["best_day_pnl"],
                    state["best_day_pct_of_total"],
                    state["trading_days"],
                ),
            )
            con.execute(
                """
                INSERT OR REPLACE INTO cache_meta (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                ("risk_filters_run_at", now_utc_iso(), now_utc_iso()),
            )
            con.commit()
        finally:
            con.close()

    _progress(f"DONE: {len(portfolio)} candidates checked in {time.time() - t0:.1f}s")
    return portfolio, state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meridian Stage 6 risk filters")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--account-balance", type=float, default=None)
    parser.add_argument("--risk-per-trade", type=float, default=None)
    parser.add_argument("--max-positions", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prop-firm", default=DEFAULT_PROP_FIRM)
    parser.add_argument("--debug", default=None)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--tickers", default=None)
    parser.add_argument("--directions", default=None)
    parser.add_argument("--size", nargs=2, metavar=("TICKER", "DIRECTION"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tickers = _csv_upper(args.tickers)
    directions = _csv_upper(args.directions)
    if args.size:
        tickers = [str(args.size[0]).upper()]
        directions = [str(args.size[1]).upper()]
    try:
        portfolio, state = build_tradeable_portfolio(
            db_path=Path(args.db).expanduser().resolve(),
            prop_firm=args.prop_firm,
            account_balance=args.account_balance,
            risk_per_trade=args.risk_per_trade,
            max_positions=args.max_positions,
            dry_run=args.dry_run,
            debug_ticker=args.debug,
            mock=args.mock,
            tickers=tickers or None,
            directions=directions or None,
        )
    except (RiskFilterError, SelectionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    if args.size and not portfolio.empty:
        row = portfolio.iloc[0]
        print(f"{row['ticker']} {row['direction']} @ ${row['entry_price']}")
        print(f"ATR(14): ${row['atr']}")
        print(f"Stop: ${row['stop_price']}")
        print(f"TP: ${row['tp_price']}")
        print(f"Risk per share: ${round(abs((row['entry_price'] or 0) - (row['stop_price'] or 0)), 2)}")
        print(f"Shares: {row['shares']} (at {row['risk_pct']}% risk = ${row['risk_dollars']})")
        print(f"Position value: ${row['position_value']}")
        verdict = row["filter_status"]
        suffix = "" if verdict == "APPROVED" else f" ({row['filter_reason']})"
        print(f"Risk check: {verdict}{suffix}")

    print(
        json.dumps(
            {
                "ok": True,
                "approved": int((portfolio["filter_status"] == "APPROVED").sum()),
                "rejected": int((portfolio["filter_status"] != "APPROVED").sum()),
                "state": state,
                "sample": portfolio.head(10).to_dict(orient="records"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
