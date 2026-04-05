#!/usr/bin/env python3
"""
Meridian Stage 2 — Prefilter.

Reads Meridian's own cache DB, applies sequential quality filters, computes
Wilder ADX / ATR for survivors only, tags regime + sector, and returns an
in-memory DataFrame for Stage 3.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stages.factors import now_et_iso, now_utc_iso, today_et


log = logging.getLogger("meridian.stage2.prefilter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "v2_universe.db"
SECTOR_MAP_PATH = ROOT / "config" / "ticker_sector_map.json"

ADX_PERIOD = 14
ATR_PERIOD = 14
MIN_WILDER_BARS = ADX_PERIOD * 2
REGIMES = {"TRENDING", "CHOPPY", "VOLATILE", "UNKNOWN"}
LEVERAGED_ETF_TICKERS = {
    "TQQQ", "SQQQ", "UPRO", "SPXU", "SPXS", "TNA", "TZA", "FAS", "FAZ",
    "LABU", "LABD", "SOXL", "SOXS", "TECL", "TECS", "CURE", "EDC", "EDZ",
    "ERX", "ERY", "NAIL", "DRV", "RETL", "MIDU", "SMDD", "UDOW", "SDOW",
    "UMDD", "URTY", "SRTY", "NUGT", "DUST", "JNUG", "JDST", "GUSH", "DRIP",
    "WEBL", "WEBS", "BULZ", "BERZ", "FNGU", "FNGD", "DPST", "HIBL", "HIBS",
    "PILL", "OOTO", "DFEN", "DUSL",
    "SSO", "SDS", "QLD", "QID", "DDM", "DXD", "MVV", "MZZ", "ROM", "REW",
    "UGE", "SZK", "UYG", "SKF", "DIG", "DUG", "UPW", "SDP", "UCC", "SCC",
    "AGQ", "ZSL", "UCO", "SCO", "BOIL", "KOLD", "UBT", "TBT", "UST", "PST",
    "ULE", "EUO", "YCL", "YCS",
    "UVXY", "SVXY", "VXX", "VIXY", "SVOL", "DOG", "SH", "PSQ", "RWM", "EFZ",
    "SEF", "EPV", "EUM", "BZQ", "LTL",
    "TSLL", "TSLS", "NVDL", "NVDS", "AMDL", "AMDS", "MSFU", "MSFD",
    "AAPU", "AAPD", "GOOU", "AMZU", "AMZD", "MSTU", "MSTD",
    "BITU", "BITD", "CONU", "COND", "DISO", "DISH", "FBL", "FBS",
    "GLL", "JETU", "JETD", "NFLR", "NFLD", "PYPL", "PYPS",
}
BOND_MONEY_MARKET_BLOCKLIST = {
    "FLOT", "VUSB", "FLRN", "GSY", "USFR", "ICSH", "JPST", "PULS", "FTSM",
    "MINT", "NEAR", "SHV", "BIL", "SGOV", "TFLO", "CLTL", "GBIL",
    "JMST", "VCSH", "SCHO", "IGSB", "BSV", "VGSH", "SHY",
    "ULST", "CARY", "CLOA", "FLTR",
    "NLY", "ARR", "AGNC", "STWD", "TWO", "MFA", "CIM", "IVR", "ORC",
    "MSTZ", "SQQQ", "TQQQ", "SPXS", "SPXL", "SARK", "ARKK",
    "QLD", "QID", "SSO", "SDS", "UVXY", "SVXY", "VIXY", "VXX",
    "QTEC", "XLY", "XLK", "XLF", "XLE", "XLV", "XLI", "XLB", "XLP", "XLU",
    "IWM", "SPY", "QQQ", "DIA", "VOO", "VTI", "IVV",
}
EXCLUDED_SUFFIXES = (".WS", ".WT", ".U", ".R", ".UN")
MIN_ATR_PCT = 0.005


class PrefilterError(RuntimeError):
    """Fatal Stage 2 error."""


def _generated_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_now_iso() -> str:
    return now_et_iso()


def _resolve_db_path(db_arg: str | None = None) -> Path:
    raw = db_arg or os.environ.get("V2_DB_PATH", str(DEFAULT_DB_PATH))
    return Path(raw).expanduser().resolve()


def _guard_db_path(db_path: Path) -> None:
    resolved = db_path.expanduser().resolve()
    if resolved.parent != DATA_DIR.resolve():
        raise PrefilterError(
            f"Refusing to use non-Meridian DB path: {resolved}. "
            "Stage 2 may only read ~/SS/Meridian/data/v2_universe.db."
        )


def _connect_db(db_path: Path) -> sqlite3.Connection:
    _guard_db_path(db_path)
    if not db_path.exists():
        raise PrefilterError(f"v2_universe.db missing at {db_path}")
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _load_sector_map() -> dict[str, str]:
    if not SECTOR_MAP_PATH.exists():
        log.warning("Sector map missing at %s", SECTOR_MAP_PATH)
        return {}
    data = json.loads(SECTOR_MAP_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PrefilterError(f"Invalid sector map JSON at {SECTOR_MAP_PATH}")
    return {str(k).upper(): str(v) for k, v in data.items()}


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _get_cache_meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute(
        "SELECT value FROM cache_meta WHERE key=?",
        (key,),
    ).fetchone()
    return str(row["value"]) if row and row["value"] is not None else None


def _require_stage1_ready(con: sqlite3.Connection) -> str:
    if not _table_exists(con, "daily_bars"):
        raise PrefilterError("daily_bars table missing in v2_universe.db")
    if not _table_exists(con, "cache_meta"):
        raise PrefilterError("cache_meta table missing in v2_universe.db")

    ticker_count = int(
        con.execute("SELECT COUNT(DISTINCT ticker) AS n FROM daily_bars").fetchone()["n"] or 0
    )
    if ticker_count <= 0:
        raise PrefilterError("daily_bars table is empty")

    spy_exists = con.execute(
        "SELECT 1 FROM daily_bars WHERE ticker='SPY' LIMIT 1"
    ).fetchone()
    if not spy_exists:
        raise PrefilterError("SPY missing from daily_bars")

    status = _get_cache_meta(con, "validation_status")
    if status is None:
        status = _get_cache_meta(con, "stage1_validation_status")
    if status is None:
        raise PrefilterError("cache_meta.validation_status missing")
    if str(status).upper() != "PASS":
        raise PrefilterError(f"cache_meta.validation_status is not PASS: {status}")
    return str(status).upper()


def _suffix_excluded(ticker: str) -> bool:
    upper = str(ticker or "").upper()
    return any(upper.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)


def _leveraged_or_inverse_excluded(ticker: str) -> bool:
    upper = str(ticker or "").upper()
    if upper in LEVERAGED_ETF_TICKERS:
        return True
    pattern_tokens = ("-3X", "-2X", "ULTRA", "BEAR", "BULL")
    return any(token in upper for token in pattern_tokens)


def _bond_money_market_excluded(ticker: str) -> bool:
    upper = str(ticker or "").upper()
    return upper in BOND_MONEY_MARKET_BLOCKLIST


def _ticker_excluded(ticker: str) -> bool:
    return (
        _suffix_excluded(ticker)
        or _leveraged_or_inverse_excluded(ticker)
        or _bond_money_market_excluded(ticker)
    )


def classify_regime(adx: float, atr_expansion: bool = False) -> str:
    if adx >= 25:
        return "TRENDING"
    if adx >= 15:
        return "CHOPPY"
    if atr_expansion:
        return "VOLATILE"
    return "UNKNOWN"


def _wilder_smooth(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    first = sum(values[:period])
    smoothed = [first]
    for value in values[period:]:
        smoothed.append(smoothed[-1] - (smoothed[-1] / period) + value)
    return smoothed


def _compute_adx_atr(highs: list[float], lows: list[float], closes: list[float]) -> tuple[float, float, bool]:
    n = len(highs)
    if n < 2 or not closes or closes[-1] <= 0:
        return 0.0, 0.0, False

    tr_vals: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for i in range(1, n):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]
        prev_high = highs[i - 1]
        prev_low = lows[i - 1]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        up_move = high - prev_high
        down_move = prev_low - low
        tr_vals.append(tr)
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    smoothed_tr = _wilder_smooth(tr_vals, ATR_PERIOD)
    if not smoothed_tr:
        return 0.0, 0.0, False

    atr_series = [value / ATR_PERIOD for value in smoothed_tr]
    latest_atr = atr_series[-1]
    atr_pct = latest_atr / closes[-1] if closes[-1] else 0.0

    atr_expansion = False
    if len(atr_series) >= 6:
        prev_window = atr_series[-6:-1]
        atr_expansion = latest_atr > (sum(prev_window) / len(prev_window))

    if n < MIN_WILDER_BARS:
        return 0.0, atr_pct, atr_expansion

    smoothed_plus = _wilder_smooth(plus_dm, ADX_PERIOD)
    smoothed_minus = _wilder_smooth(minus_dm, ADX_PERIOD)
    if not smoothed_plus or not smoothed_minus:
        return 0.0, atr_pct, atr_expansion

    dx_vals: list[float] = []
    for tr, p_dm, m_dm in zip(smoothed_tr, smoothed_plus, smoothed_minus):
        if tr <= 0:
            dx_vals.append(0.0)
            continue
        plus_di = 100.0 * p_dm / tr
        minus_di = 100.0 * m_dm / tr
        denom = plus_di + minus_di
        dx_vals.append(0.0 if denom <= 0 else 100.0 * abs(plus_di - minus_di) / denom)

    adx_smoothed = _wilder_smooth(dx_vals, ADX_PERIOD)
    adx = adx_smoothed[-1] / ADX_PERIOD if adx_smoothed else 0.0
    return adx, atr_pct, atr_expansion


def _query_initial_stats(con: sqlite3.Connection) -> "pd.DataFrame":
    if pd is None:
        raise PrefilterError("pandas is required for Stage 2")
    sql = """
    WITH ranked AS (
        SELECT
            ticker,
            date,
            close,
            volume,
            ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
        FROM daily_bars
    )
    SELECT
        ticker,
        MAX(CASE WHEN rn = 1 THEN close END) AS latest_close,
        MAX(CASE WHEN rn = 1 THEN date END) AS latest_date,
        SUM(CASE WHEN close IS NOT NULL AND close > 0 THEN 1 ELSE 0 END) AS bars_available,
        AVG(CASE WHEN rn <= 20 THEN close * volume END) AS dollar_volume
    FROM ranked
    GROUP BY ticker
    ORDER BY ticker ASC
    """
    return pd.read_sql_query(sql, con)


def _load_survivor_bars(con: sqlite3.Connection, tickers: list[str]) -> "pd.DataFrame":
    if pd is None:
        raise PrefilterError("pandas is required for Stage 2")
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", "high", "low", "close", "volume"])
    placeholders = ",".join("?" * len(tickers))
    sql = f"""
        SELECT ticker, date, high, low, close, volume
        FROM daily_bars
        WHERE ticker IN ({placeholders})
        ORDER BY ticker ASC, date ASC
    """
    return pd.read_sql_query(sql, con, params=tickers)


def _write_prefilter_stats(
    con: sqlite3.Connection,
    *,
    input_count: int,
    survivor_count: int,
    excluded_price: int,
    excluded_volume: int,
    excluded_suffix: int,
    excluded_bars: int,
    excluded_low_vol: int,
    regime_distribution: dict[str, int],
) -> None:
    rows = {
        "prefilter_input_count": str(input_count),
        "prefilter_survivors": str(survivor_count),
        "prefilter_excluded_price": str(excluded_price),
        "prefilter_excluded_volume": str(excluded_volume),
        "prefilter_excluded_suffix": str(excluded_suffix),
        "prefilter_excluded_bars": str(excluded_bars),
        "prefilter_excluded_low_vol": str(excluded_low_vol),
        "prefilter_regime_distribution": json.dumps(regime_distribution, sort_keys=True),
        "prefilter_run_at": now_utc_iso(),
    }
    con.executemany(
        """
        INSERT OR REPLACE INTO cache_meta (key, value, updated_at)
        VALUES (?, ?, ?)
        """,
        [(key, value, now_utc_iso()) for key, value in rows.items()],
    )
    con.commit()


def _ensure_prefilter_results_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS prefilter_results (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            regime TEXT,
            price REAL,
            dollar_volume REAL,
            bars_available INTEGER,
            atr_pct REAL,
            adx REAL,
            sector TEXT,
            PRIMARY KEY (date, ticker)
        )
        """
    )
    con.commit()


def _write_prefilter_results(con: sqlite3.Connection, frame: "pd.DataFrame", run_date: str) -> None:
    _ensure_prefilter_results_table(con)
    con.execute("DELETE FROM prefilter_results WHERE date = ?", (run_date,))
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            (
                run_date,
                str(row["ticker"]).upper(),
                row["regime"],
                float(row["price"]) if pd.notna(row["price"]) else None,
                float(row["dollar_volume"]) if pd.notna(row["dollar_volume"]) else None,
                int(row["bars_available"]) if pd.notna(row["bars_available"]) else None,
                float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else None,
                float(row["adx"]) if pd.notna(row["adx"]) else None,
                row["sector"],
            )
        )
    con.executemany(
        """
        INSERT OR REPLACE INTO prefilter_results (
            date, ticker, regime, price, dollar_volume,
            bars_available, atr_pct, adx, sector
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()


def run_prefilter(
    db_path: str | Path | None = None,
    *,
        min_price: float = 1.0,
        min_dollar_volume: float = 200_000.0,
        min_bars: int = 50,
        min_atr_pct: float = MIN_ATR_PCT,
        dry_run: bool = False,
) -> "pd.DataFrame":
    if pd is None:
        raise PrefilterError("pandas is required for Stage 2")
    resolved_db = _resolve_db_path(str(db_path) if db_path is not None else None)
    con = _connect_db(resolved_db)
    try:
        validation_status = _require_stage1_ready(con)
        stats = _query_initial_stats(con)
        if stats.empty:
            raise PrefilterError("No ticker aggregates returned from daily_bars")

        stats["ticker"] = stats["ticker"].astype(str).str.upper()
        stats["latest_close"] = pd.to_numeric(stats["latest_close"], errors="coerce")
        stats["bars_available"] = pd.to_numeric(stats["bars_available"], errors="coerce").fillna(0).astype(int)
        stats["dollar_volume"] = pd.to_numeric(stats["dollar_volume"], errors="coerce").fillna(0.0)

        input_count = len(stats)

        stage = stats.copy()
        price_mask = (stage["latest_close"] >= min_price) | (stage["ticker"] == "SPY")
        excluded_price = int((~price_mask).sum())
        stage = stage[price_mask].copy()

        volume_mask = (stage["dollar_volume"] >= min_dollar_volume) | (stage["ticker"] == "SPY")
        excluded_volume = int((~volume_mask).sum())
        stage = stage[volume_mask].copy()

        suffix_mask = (~stage["ticker"].map(_ticker_excluded)) | (stage["ticker"] == "SPY")
        excluded_suffix = int((~suffix_mask).sum())
        stage = stage[suffix_mask].copy()

        bars_mask = (stage["bars_available"] >= min_bars) | (stage["ticker"] == "SPY")
        excluded_bars = int((~bars_mask).sum())
        stage = stage[bars_mask].copy()

        if stage.empty:
            raise PrefilterError("survivor_count = 0")

        tickers = stage["ticker"].tolist()
        bars_df = _load_survivor_bars(con, tickers)
        sector_map = _load_sector_map()

        rows: list[dict[str, Any]] = []
        for ticker in tickers:
            ticker_bars = bars_df[bars_df["ticker"] == ticker]
            highs = pd.to_numeric(ticker_bars["high"], errors="coerce").dropna().tolist()
            lows = pd.to_numeric(ticker_bars["low"], errors="coerce").dropna().tolist()
            closes = pd.to_numeric(ticker_bars["close"], errors="coerce").dropna().tolist()
            if not closes:
                continue
            adx, atr_pct, atr_expansion = _compute_adx_atr(highs, lows, closes)
            regime = classify_regime(adx, atr_expansion)
            meta = stage.loc[stage["ticker"] == ticker].iloc[0]
            rows.append(
                {
                    "ticker": ticker,
                    "regime": regime,
                    "price": float(meta["latest_close"]),
                    "dollar_volume": float(meta["dollar_volume"]),
                    "bars_available": int(meta["bars_available"]),
                    "atr_pct": float(atr_pct),
                    "adx": float(adx),
                    "sector": sector_map.get(ticker),
                }
            )

        out = pd.DataFrame(
            rows,
            columns=["ticker", "regime", "price", "dollar_volume", "bars_available", "atr_pct", "adx", "sector"],
        ).sort_values(["ticker"]).reset_index(drop=True)

        if out.empty:
            raise PrefilterError("survivor_count = 0")

        low_vol_mask = (out["atr_pct"] >= min_atr_pct) | (out["ticker"] == "SPY")
        excluded_low_vol = int((~low_vol_mask).sum())
        out = out[low_vol_mask].copy()

        if out.empty:
            raise PrefilterError("survivor_count = 0 after low-volatility filter")

        if "SPY" not in set(out["ticker"].tolist()):
            raise PrefilterError("SPY did not survive Stage 2 filters")

        regime_distribution = {
            key: int(value)
            for key, value in out["regime"].value_counts().sort_index().to_dict().items()
        }

        if not dry_run:
            run_date = today_et()
            _write_prefilter_results(con, out, run_date)
            _write_prefilter_stats(
                con,
                input_count=input_count,
                survivor_count=len(out),
                excluded_price=excluded_price,
                excluded_volume=excluded_volume,
                excluded_suffix=excluded_suffix,
                excluded_bars=excluded_bars,
                excluded_low_vol=excluded_low_vol,
                regime_distribution=regime_distribution,
            )

        if len(out) < 1000:
            log.warning("Prefilter survivors low: %d", len(out))
        if len(out) > 6000:
            log.warning("Prefilter survivors high: %d", len(out))
        if regime_distribution.get("UNKNOWN", 0) > len(out) * 0.30:
            log.warning("UNKNOWN regime exceeds 30%% of survivors")

        out.attrs["stats"] = {
            "validation_status": validation_status,
            "input_count": input_count,
            "survivors": len(out),
            "excluded_price": excluded_price,
            "excluded_volume": excluded_volume,
            "excluded_suffix": excluded_suffix,
            "excluded_bars": excluded_bars,
            "excluded_low_vol": excluded_low_vol,
            "regime_distribution": regime_distribution,
            "sql_initial_filter": _query_initial_stats.__doc__ if False else "window_aggregate",
        }
        return out
    finally:
        con.close()


def _build_summary(df: "pd.DataFrame") -> dict[str, Any]:
    stats = dict(df.attrs.get("stats", {}))
    return {
        "ok": True,
        "generated_at": _generated_at_utc(),
        "survivors": len(df),
        "columns": list(df.columns),
        "stats": stats,
        "sample": df.head(10).to_dict(orient="records"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meridian Stage 2 prefilter")
    parser.add_argument("--db", default=None, help="Override V2 DB path")
    parser.add_argument("--min-price", type=float, default=1.0)
    parser.add_argument("--min-dollar-volume", type=float, default=200_000.0)
    parser.add_argument("--min-bars", type=int, default=50)
    parser.add_argument("--min-atr-pct", type=float, default=MIN_ATR_PCT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        df = run_prefilter(
            args.db,
            min_price=args.min_price,
            min_dollar_volume=args.min_dollar_volume,
            min_bars=args.min_bars,
            min_atr_pct=args.min_atr_pct,
            dry_run=args.dry_run,
        )
        print(json.dumps(_build_summary(df), indent=2))
        return 0
    except PrefilterError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "generated_at": _generated_at_utc(),
                },
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
