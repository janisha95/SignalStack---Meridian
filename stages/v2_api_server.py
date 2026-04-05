#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stages.factors import compute_atr, now_et_iso
from stages.v2_risk_filters import compute_position, load_risk_config
from stages.v2_forward_tracker import build_summary as _ft_build_summary, ensure_table as _ft_ensure_table


STAGE_NAME = "api"
ROOT = Path(__file__).resolve().parents[1]
ALPACA_PAPER_BASE = "https://paper-api.alpaca.markets"
DEFAULT_DB_PATH = ROOT / "data" / "v2_universe.db"
RISK_CONFIG_PATH = ROOT / "config" / "risk_config.json"
FUNDAMENTAL_CACHE_PATH = ROOT / "data" / "fundamental_cache.json"


def _progress(message: str) -> None:
    print(f"[{STAGE_NAME}] {message}", flush=True)


def _connect_db(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
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


def _latest_date(con: sqlite3.Connection, table: str) -> str | None:
    if not _table_exists(con, table):
        return None
    row = con.execute(f"SELECT MAX(date) AS d FROM {table}").fetchone()
    return str(row["d"]) if row and row["d"] is not None else None


def _get_meta(con: sqlite3.Connection, key: str) -> str | None:
    if not _table_exists(con, "cache_meta"):
        return None
    row = con.execute("SELECT value FROM cache_meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row and row["value"] is not None else None


def _safe_rows(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in con.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []


def _safe_one(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    try:
        row = con.execute(sql, params).fetchone()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


def _default_portfolio_state() -> dict[str, Any]:
    return {
        "date": None,
        "account_balance": 100000.0,
        "daily_pnl": 0.0,
        "total_pnl": 0.0,
        "total_pnl_pct": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
        "open_positions": 0,
        "portfolio_heat_pct": 0.0,
        "daily_loss_remaining": 5000.0,
        "drawdown_remaining": 10000.0,
        "distance_to_target": 10000.0,
        "best_day_pnl": 0.0,
        "best_day_pct_of_total": 0.0,
        "trading_days": 0,
    }


def _normalize_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        top_shap = row.get("top_shap_factors")
        if isinstance(top_shap, str):
            try:
                top_shap = json.loads(top_shap)
            except Exception:
                top_shap = [top_shap]
        out.append(
            {
                "ticker": row.get("ticker"),
                "direction": row.get("direction"),
                "predicted_return": None,
                "residual_alpha": row.get("residual_alpha", 0),
                "beta": row.get("beta"),
                "regime": row.get("regime"),
                "sector": row.get("sector"),
                "price": row.get("price"),
                "rank": row.get("rank"),
                "factor_rank": row.get("factor_rank"),
                "tcn_long_score": row.get("tcn_long_score"),
                "tcn_short_score": row.get("tcn_short_score"),
                "tcn_score": row.get("tcn_score", 0.5),
                "final_score": row.get("final_score", 0),
                "top_shap_factors": top_shap,
            }
        )
    return out


def _load_settings() -> dict[str, Any]:
    if not RISK_CONFIG_PATH.exists():
        return {}
    return json.loads(RISK_CONFIG_PATH.read_text(encoding="utf-8"))


def _load_sector_cache() -> dict[str, str]:
    if not FUNDAMENTAL_CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(FUNDAMENTAL_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for ticker, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            sector = payload.get("sector")
            if sector:
                out[str(ticker).upper()] = str(sector)
    return out


SECTOR_CACHE = _load_sector_cache()


def _load_latest_price_and_atr(con: sqlite3.Connection, ticker: str) -> tuple[float | None, float | None]:
    price = None
    atr = None
    if _table_exists(con, "prefilter_results"):
        run_date = _latest_date(con, "prefilter_results")
        if run_date:
            row = con.execute(
                """
                SELECT price, atr_pct
                FROM prefilter_results
                WHERE date = ? AND ticker = ?
                """,
                (run_date, ticker),
            ).fetchone()
            if row:
                price = float(row["price"]) if row["price"] is not None else None
                atr_pct = float(row["atr_pct"]) if row["atr_pct"] is not None else None
                if price and atr_pct is not None:
                    atr = price * atr_pct
    if atr is not None and price is not None:
        return price, atr
    if not _table_exists(con, "daily_bars"):
        return price, atr
    bars = con.execute(
        """
        WITH ranked AS (
            SELECT ticker, date, open, high, low, close, volume,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM daily_bars
            WHERE ticker = ?
        )
        SELECT ticker, date, open, high, low, close, volume
        FROM ranked
        WHERE rn <= 120
        ORDER BY date ASC
        """,
        (ticker,),
    ).fetchall()
    if not bars:
        return price, atr
    import pandas as pd

    df = pd.DataFrame([dict(r) for r in bars])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    price = float(df["close"].iloc[-1]) if not df.empty else price
    atr_series = compute_atr(df.copy(), 14)
    if not atr_series.empty and atr_series.iloc[-1] == atr_series.iloc[-1]:
        atr = float(atr_series.iloc[-1])
    return price, atr


class SizeRequest(BaseModel):
    ticker: str
    direction: str


class TradeRequest(BaseModel):
    ticker: str
    direction: str   # "LONG" or "SHORT"
    shares: float
    price: float     # expected entry price (for bracket calc)
    atr: float | None = None  # optional; falls back to 2% of price


def _alpaca_paper_request(
    method: str, path: str, body: dict[str, Any] | None, api_key: str, api_secret: str
) -> dict[str, Any]:
    url = f"{ALPACA_PAPER_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("APCA-API-KEY-ID", api_key)
    req.add_header("APCA-API-SECRET-KEY", api_secret)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def create_app(db_path: Path = DEFAULT_DB_PATH) -> FastAPI:
    app = FastAPI(title="Meridian API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "timestamp": now_et_iso()}

    @app.get("/api/portfolio/state")
    def get_portfolio_state() -> dict[str, Any]:
        con = _connect_db(db_path)
        try:
            latest = _latest_date(con, "portfolio_state")
            if not latest:
                return _default_portfolio_state()
            row = _safe_one(con, "SELECT * FROM portfolio_state WHERE date = ?", (latest,))
            return row or _default_portfolio_state()
        finally:
            con.close()

    @app.get("/api/candidates")
    def get_candidates() -> list[dict[str, Any]]:
        con = _connect_db(db_path)
        try:
            latest = _latest_date(con, "shortlist_daily")
            if not latest:
                return []
            try:
                rows = [dict(row) for row in con.execute(
                    """
                    SELECT ticker, direction, predicted_return,
                           residual_alpha, beta, regime, sector, price, rank,
                           factor_rank, tcn_long_score, tcn_short_score,
                           COALESCE(
                               CASE
                                   WHEN UPPER(direction) = 'LONG' THEN tcn_long_score
                                   WHEN UPPER(direction) = 'SHORT' THEN tcn_short_score
                               END,
                               tcn_score,
                               0.5
                           ) AS tcn_score,
                           COALESCE(
                               final_score,
                               CASE
                                   WHEN UPPER(direction) = 'LONG' THEN tcn_long_score
                                   WHEN UPPER(direction) = 'SHORT' THEN tcn_short_score
                               END,
                               0
                           ) AS final_score,
                           top_shap_factors
                    FROM shortlist_daily
                    WHERE date = ?
                    ORDER BY direction ASC, rank ASC, ticker ASC
                    """,
                    (latest,),
                ).fetchall()]
            except sqlite3.Error:
                rows = _safe_rows(
                    con,
                    """
                    SELECT ticker, direction, predicted_return,
                           residual_alpha, beta, regime, sector, price, rank,
                           factor_rank, tcn_score, final_score,
                           top_shap_factors
                    FROM shortlist_daily
                    WHERE date = ?
                    ORDER BY direction ASC, rank ASC, ticker ASC
                    """,
                    (latest,),
                )
            normalized = _normalize_candidate_rows(rows)
            for row in normalized:
                ticker = str(row.get("ticker") or "").upper()
                sector = row.get("sector")
                if not sector or str(sector).strip().lower() in {"unknown", "none", "null", ""}:
                    row["sector"] = SECTOR_CACHE.get(ticker, "Unknown")
            return normalized
        finally:
            con.close()

    @app.get("/api/v2/scan")
    def scan_v2() -> list[dict[str, Any]]:
        return get_candidates()

    @app.get("/api/v2/ticker/{ticker}")
    def get_ticker_info(ticker: str) -> dict[str, Any]:
        clean_ticker = ticker.upper().replace(".US", "")
        try:
            import yfinance as yf

            inst = yf.Ticker(clean_ticker)
            fast_info = dict(getattr(inst, "fast_info", {}) or {})
            info = {}
            try:
                info = dict(getattr(inst, "info", {}) or {})
            except Exception:
                info = {}

            def _pick_float(*values: Any) -> float | None:
                for value in values:
                    if value is None:
                        continue
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
                return None

            def _pick_int(*values: Any) -> int | None:
                for value in values:
                    if value is None:
                        continue
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        continue
                return None

            last_price = _pick_float(
                info.get("currentPrice"),
                info.get("regularMarketPrice"),
                fast_info.get("lastPrice"),
                fast_info.get("last_price"),
            )
            previous_close = _pick_float(
                info.get("previousClose"),
                info.get("regularMarketPreviousClose"),
                fast_info.get("previousClose"),
                fast_info.get("previous_close"),
            )
            open_price = _pick_float(info.get("open"), info.get("regularMarketOpen"), fast_info.get("open"))
            day_high = _pick_float(
                info.get("dayHigh"),
                info.get("regularMarketDayHigh"),
                fast_info.get("dayHigh"),
                fast_info.get("day_high"),
            )
            day_low = _pick_float(
                info.get("dayLow"),
                info.get("regularMarketDayLow"),
                fast_info.get("dayLow"),
                fast_info.get("day_low"),
            )
            volume = _pick_int(
                info.get("volume"),
                info.get("regularMarketVolume"),
                fast_info.get("lastVolume"),
                fast_info.get("last_volume"),
            )
            market_cap = _pick_float(info.get("marketCap"), fast_info.get("marketCap"), fast_info.get("market_cap"))
            year_high = _pick_float(info.get("fiftyTwoWeekHigh"), fast_info.get("yearHigh"), fast_info.get("year_high"))
            year_low = _pick_float(info.get("fiftyTwoWeekLow"), fast_info.get("yearLow"), fast_info.get("year_low"))

            if last_price is None or previous_close is None:
                try:
                    hist = inst.history(period="5d")
                    if not hist.empty:
                        if last_price is None:
                            last_price = float(hist["Close"].iloc[-1])
                        if previous_close is None and len(hist) > 1:
                            previous_close = float(hist["Close"].iloc[-2])
                        if open_price is None:
                            open_price = float(hist["Open"].iloc[-1])
                        if day_high is None:
                            day_high = float(hist["High"].iloc[-1])
                        if day_low is None:
                            day_low = float(hist["Low"].iloc[-1])
                        if volume is None:
                            volume = int(hist["Volume"].iloc[-1])
                except Exception:
                    pass

            if last_price is not None and previous_close and previous_close > 0:
                change_pct = ((last_price - previous_close) / previous_close) * 100.0
            else:
                change_pct = None
            return {
                "ticker": clean_ticker,
                "name": info.get("shortName") or info.get("longName") or clean_ticker,
                "exchange": info.get("exchange"),
                "price": last_price,
                "open": open_price,
                "previous_close": previous_close,
                "day_high": day_high,
                "day_low": day_low,
                "volume": volume,
                "market_cap": market_cap,
                "fifty_two_week_high": year_high,
                "fifty_two_week_low": year_low,
                "change_pct": change_pct,
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            }
        except Exception as exc:
            return {
                "ticker": clean_ticker,
                "name": clean_ticker,
                "price": None,
                "open": None,
                "previous_close": None,
                "day_high": None,
                "day_low": None,
                "volume": None,
                "market_cap": None,
                "fifty_two_week_high": None,
                "fifty_two_week_low": None,
                "change_pct": None,
                "error": str(exc),
            }

    @app.get("/api/positions")
    def get_positions() -> list[dict[str, Any]]:
        con = _connect_db(db_path)
        try:
            latest = _latest_date(con, "tradeable_portfolio")
            if not latest:
                return []
            return _safe_rows(
                con,
                """
                SELECT date, ticker, direction, shares, entry_price, stop_price, tp_price,
                       risk_dollars, risk_pct, position_value, atr, sector, regime,
                       rank, predicted_return, beta, residual_alpha, filter_status, filter_reason
                FROM tradeable_portfolio
                WHERE date = ? AND filter_status = 'APPROVED'
                ORDER BY direction ASC, rank ASC, ticker ASC
                """,
                (latest,),
            )
        finally:
            con.close()

    @app.get("/api/trades/log")
    def get_trade_log() -> list[dict[str, Any]]:
        con = _connect_db(db_path)
        try:
            if not _table_exists(con, "trade_log"):
                return []
            return _safe_rows(
                con,
                """
                SELECT ticker, direction, entry_date, entry_price, shares, exit_date,
                       exit_price, exit_reason, pnl_dollars, pnl_pct, hold_days, risk_dollars
                FROM trade_log
                ORDER BY COALESCE(entry_date, exit_date) DESC, id DESC
                LIMIT 100
                """,
            )
        finally:
            con.close()

    @app.get("/api/model/health")
    def get_model_health() -> dict[str, Any]:
        con = _connect_db(db_path)
        try:
            latest = _latest_date(con, "orchestrator_log")
            rows = _safe_rows(
                con,
                "SELECT stage, status, elapsed_seconds, detail FROM orchestrator_log WHERE date = ? ORDER BY CAST(stage AS INTEGER) ASC",
                (latest,),
            ) if latest else []
            status = "OK"
            if rows and any(str(row["status"]).upper() in {"FAIL", "ERROR"} for row in rows):
                status = "FAIL"
            elif rows and any(str(row["status"]).upper() == "MOCK" for row in rows):
                status = "MOCK"
            elapsed = round(sum(float(row.get("elapsed_seconds") or 0.0) for row in rows), 3)
            training_rows = 0
            if _table_exists(con, "training_data"):
                training_rows = int(con.execute("SELECT COUNT(*) FROM training_data").fetchone()[0] or 0)
            feature_count = 0
            if _table_exists(con, "factor_matrix_daily"):
                cols = [r["name"] for r in con.execute("PRAGMA table_info(factor_matrix_daily)").fetchall()]
                feature_count = max(0, len(cols) - 3)
            return {
                "last_run": _get_meta(con, "risk_filters_run_at") or _get_meta(con, "factor_engine_run_at") or latest,
                "pipeline_status": status,
                "pipeline_elapsed_s": elapsed,
                "model_version": _get_meta(con, "model_version") or "mock",
                "last_retrain": _get_meta(con, "last_retrain"),
                "rolling_ic": _get_meta(con, "rolling_ic"),
                "feature_count": feature_count,
                "training_rows": training_rows,
            }
        finally:
            con.close()

    @app.get("/api/model/factors")
    def get_model_factors() -> dict[str, Any]:
        con = _connect_db(db_path)
        try:
            latest = _latest_date(con, "factor_matrix_daily")
            if not latest:
                return {}
            row = con.execute(
                """
                SELECT *
                FROM factor_matrix_daily
                WHERE date = ?
                ORDER BY ticker ASC
                LIMIT 1
                """,
                (latest,),
            ).fetchone()
            return dict(row) if row else {}
        finally:
            con.close()

    @app.get("/api/tracking/summary")
    def get_tracking_summary() -> dict[str, Any]:
        _ft_ensure_table(db_path)
        return _ft_build_summary(db_path)

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return _load_settings()

    @app.post("/api/risk/size")
    def post_risk_size(body: SizeRequest) -> dict[str, Any]:
        ticker = body.ticker.upper()
        direction = body.direction.upper()
        con = _connect_db(db_path)
        try:
            config = load_risk_config()
            latest_state = _latest_date(con, "portfolio_state")
            portfolio_state = (
                _safe_one(con, "SELECT * FROM portfolio_state WHERE date = ?", (latest_state,))
                if latest_state
                else None
            ) or {
                "daily_loss_remaining": float(config["max_daily_loss_pct"]) * float(config["account_balance"]),
                "drawdown_remaining": float(config["max_total_drawdown_pct"]) * float(config["account_balance"]),
            }
            price, atr = _load_latest_price_and_atr(con, ticker)
            if price is None or atr is None:
                return {
                    "ticker": ticker,
                    "direction": direction,
                    "error": "Ticker not found or ATR unavailable",
                }
            result = compute_position(ticker, direction, float(price), float(atr), config, portfolio_state)
            if result is None:
                return {
                    "ticker": ticker,
                    "direction": direction,
                    "error": "Position sizing rejected by risk budget",
                }
            result.update({"ticker": ticker, "direction": direction, "sized_at": now_et_iso()})
            return result
        finally:
            con.close()

    @app.post("/api/v2/trade")
    def place_trade(body: TradeRequest) -> dict[str, Any]:
        api_key = os.environ.get("ALPACA_KEY", "")
        api_secret = os.environ.get("ALPACA_SECRET", "")
        if not api_key or not api_secret:
            return {"ok": False, "error": "ALPACA_KEY and ALPACA_SECRET env vars required"}
        ticker = body.ticker.upper().replace(".US", "")
        side = "buy" if body.direction.upper() == "LONG" else "sell"
        atr = body.atr if body.atr and body.atr > 0 else body.price * 0.02
        if body.direction.upper() == "LONG":
            stop = round(body.price - atr * 1.25, 2)
            tp = round(body.price + atr * 2.5, 2)
        else:
            stop = round(body.price + atr * 1.25, 2)
            tp = round(body.price - atr * 2.5, 2)
        order_body = {
            "symbol": ticker,
            "qty": str(int(body.shares)),
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket",
            "take_profit": {"limit_price": str(tp)},
            "stop_loss": {"stop_price": str(stop)},
        }
        try:
            order = _alpaca_paper_request("POST", "/v2/orders", order_body, api_key, api_secret)
            return {
                "ok": True,
                "order_id": order.get("id"),
                "ticker": ticker,
                "direction": body.direction.upper(),
                "shares": int(body.shares),
                "stop": stop,
                "take_profit": tp,
                "status": order.get("status"),
            }
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            return {"ok": False, "error": f"Alpaca {exc.code}: {detail}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/v2/positions")
    def get_alpaca_positions() -> dict[str, Any]:
        api_key = os.environ.get("ALPACA_KEY", "")
        api_secret = os.environ.get("ALPACA_SECRET", "")
        if not api_key or not api_secret:
            return {"ok": False, "error": "ALPACA_KEY and ALPACA_SECRET env vars required"}
        try:
            positions = _alpaca_paper_request("GET", "/v2/positions", None, api_key, api_secret)
            return {"ok": True, "positions": positions}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/v2/account")
    def get_alpaca_account() -> dict[str, Any]:
        api_key = os.environ.get("ALPACA_KEY", "")
        api_secret = os.environ.get("ALPACA_SECRET", "")
        if not api_key or not api_secret:
            return {"ok": False, "error": "ALPACA_KEY and ALPACA_SECRET env vars required"}
        try:
            account = _alpaca_paper_request("GET", "/v2/account", None, api_key, api_secret)
            return {
                "ok": True,
                "balance": float(account.get("equity", 0)),
                "buying_power": float(account.get("buying_power", 0)),
                "cash": float(account.get("cash", 0)),
                "portfolio_value": float(account.get("portfolio_value", 0)),
                "status": account.get("status"),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meridian API server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    args = parse_args(argv)
    db_path = Path(args.db).expanduser().resolve()
    _progress(f"Starting API server on {args.host}:{args.port}")
    _progress(f"DB: {db_path}")
    uvicorn.run(create_app(db_path), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
