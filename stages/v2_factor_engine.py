#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.factor_registry import get_active_features
from stages.factors import nan_dict, now_et_iso, now_utc_iso, today_et
from stages.factors import m1_technical_core, m2_structural_phase, m3_damage_shortside, m4_mean_reversion, m5_market_context
from stages.v2_prefilter import PrefilterError, run_prefilter


STAGE_NAME = "factor_engine"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "v2_universe.db"
REGISTRY_PATH = ROOT / "config" / "factor_registry.json"
SECTOR_MAP_PATH = ROOT / "config" / "ticker_sector_map.json"
MODULES = [
    ("m1_technical_core", m1_technical_core),
    ("m2_structural_phase", m2_structural_phase),
    ("m3_damage_shortside", m3_damage_shortside),
    ("m4_mean_reversion", m4_mean_reversion),
    ("m5_market_context", m5_market_context),
]


class FactorEngineError(RuntimeError):
    pass


def _progress(message: str) -> None:
    print(f"[{STAGE_NAME}] {message}", flush=True)


def _connect_db(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        raise FactorEngineError(f"factor_registry.json missing at {REGISTRY_PATH}")
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _active_registry_entries(registry: dict[str, Any]) -> list[dict[str, Any]]:
    active_names = get_active_features(REGISTRY_PATH)
    entries: list[dict[str, Any]] = []
    module_factor_names = {
        "m1_technical_core": set(m1_technical_core.FACTOR_NAMES),
        "m2_structural_phase": set(m2_structural_phase.FACTOR_NAMES),
        "m3_damage_shortside": set(m3_damage_shortside.FACTOR_NAMES),
        "m4_mean_reversion": set(m4_mean_reversion.FACTOR_NAMES),
        "m5_market_context": set(m5_market_context.FACTOR_NAMES),
    }
    for name in active_names:
        module_name = next(
            (module for module, factors in module_factor_names.items() if name in factors),
            None,
        )
        if module_name is None:
            continue
        entries.append({"name": name, "module": module_name, "active": True})
    return entries


def _load_sector_map() -> dict[str, str]:
    if not SECTOR_MAP_PATH.exists():
        return {}
    data = json.loads(SECTOR_MAP_PATH.read_text(encoding="utf-8"))
    return {str(k).upper(): str(v) for k, v in data.items()}


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _get_meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM cache_meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row and row["value"] is not None else None


def _load_ohlcv_map(db_path: Path, tickers: list[str]) -> dict[str, pd.DataFrame]:
    if not tickers:
        return {}
    con = _connect_db(db_path)
    try:
        frames: list[pd.DataFrame] = []
        chunk_size = 900
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            sql = f"""
                SELECT ticker, date, open, high, low, close, volume
                FROM daily_bars
                WHERE ticker IN ({placeholders})
                ORDER BY ticker ASC, date ASC
            """
            frames.append(pd.read_sql_query(sql, con, params=chunk))
    finally:
        con.close()
    full = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out: dict[str, pd.DataFrame] = {}
    for ticker, frame in full.groupby("ticker", sort=False):
        df = frame.reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.attrs["ticker"] = str(ticker).upper()
        out[str(ticker).upper()] = df
    return out


def _load_options_map(db_path: Path, tickers: list[str]) -> dict[str, dict[str, float]]:
    if not tickers:
        return {}
    con = _connect_db(db_path)
    try:
        chunk_size = 900
        rows: list[sqlite3.Row] = []
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            sql = f"""
                SELECT o1.ticker, o1.pcr, o1.unusual_vol_ratio
                FROM options_daily o1
                JOIN (
                    SELECT ticker, MAX(date) AS max_date
                    FROM options_daily
                    WHERE ticker IN ({placeholders})
                    GROUP BY ticker
                ) latest
                  ON latest.ticker = o1.ticker AND latest.max_date = o1.date
            """
            rows.extend(con.execute(sql, chunk).fetchall())
    finally:
        con.close()
    return {
        str(row["ticker"]).upper(): {
            "options_pcr": float(row["pcr"]) if row["pcr"] is not None else float("nan"),
            "options_unusual_vol": float(row["unusual_vol_ratio"]) if row["unusual_vol_ratio"] is not None else float("nan"),
        }
        for row in rows
    }


def _pick_vix_history(ohlcv_map: dict[str, pd.DataFrame]) -> tuple[pd.Series, float]:
    for ticker, scale in (("VIXY", 10.0), ("VXX", 1.0)):
        df = ohlcv_map.get(ticker)
        if df is not None and len(df) >= 20:
            close = pd.to_numeric(df["close"], errors="coerce").astype(float) * scale
            return close, float(close.iloc[-1])
    series = pd.Series([20.0] * 252, dtype=float)
    return series, 20.0


def compute_universe_stats(
    all_ohlcv: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    vix_history: pd.Series,
    sector_map: dict[str, str],
    options_map: dict[str, dict[str, float]],
) -> dict[str, Any]:
    sector_returns: dict[str, list[float]] = {}
    above_ma50 = 0
    total = 0
    up = 0
    down = 0
    for ticker, df in all_ohlcv.items():
        if ticker in {"SPY", "VIXY", "VXX"}:
            continue
        if len(df) < 50:
            continue
        close = pd.to_numeric(df["close"], errors="coerce").astype(float)
        ma50 = close.rolling(50).mean()
        latest = float(close.iloc[-1])
        if not pd.isna(ma50.iloc[-1]) and latest > ma50.iloc[-1]:
            above_ma50 += 1
        total += 1
        if len(close) >= 2:
            if close.iloc[-1] > close.iloc[-2]:
                up += 1
            elif close.iloc[-1] < close.iloc[-2]:
                down += 1
        sector = sector_map.get(ticker)
        if sector and len(close) >= 11 and close.iloc[-11] not in (0, None):
            sector_returns.setdefault(sector, []).append((latest / close.iloc[-11]) - 1.0)

    spy_5d = float("nan")
    if len(spy_df) >= 6 and float(spy_df["close"].iloc[-6]) != 0:
        spy_5d = float((spy_df["close"].iloc[-1] / spy_df["close"].iloc[-6]) - 1.0)
    vix_pct = float("nan")
    lookback = min(252, len(vix_history))
    if lookback >= 20:
        current = float(vix_history.iloc[-1])
        vix_pct = float((vix_history.tail(lookback) <= current).mean())

    return {
        "market_breadth": above_ma50 / total if total else 0.5,
        "advance_decline_ratio": up / max(down, 1),
        "sector_returns": {sector: float(sum(vals) / len(vals)) for sector, vals in sector_returns.items()},
        "spy_5d_return": spy_5d,
        "vix_252d_percentile": vix_pct,
        "options_map": options_map,
    }


def _validate_registry(registry: dict[str, Any]) -> tuple[list[str], dict[str, list[str]]]:
    module_names = {
        "m1_technical_core": set(m1_technical_core.FACTOR_NAMES),
        "m2_structural_phase": set(m2_structural_phase.FACTOR_NAMES),
        "m3_damage_shortside": set(m3_damage_shortside.FACTOR_NAMES),
        "m4_mean_reversion": set(m4_mean_reversion.FACTOR_NAMES),
        "m5_market_context": set(m5_market_context.FACTOR_NAMES),
    }
    warnings: list[str] = []
    grouped: dict[str, list[str]] = {}
    for entry in _active_registry_entries(registry):
        module = str(entry["module"])
        name = str(entry["name"])
        grouped.setdefault(module, []).append(name)
        if name not in module_names.get(module, set()):
            warnings.append(f"Registry factor {name} missing in module {module}")
    return warnings, grouped


def _module_nan_dict(module_name: str, active_by_module: dict[str, list[str]]) -> dict[str, float]:
    return nan_dict(active_by_module.get(module_name, []))


def _process_ticker(
    ticker: str,
    pref_row: dict[str, Any],
    ohlcv_map: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    vix_value: float,
    universe_stats: dict[str, Any],
    sector_map: dict[str, str],
    active_by_module: dict[str, list[str]],
) -> dict[str, Any]:
    df = ohlcv_map.get(ticker)
    if df is None or df.empty:
        raise FactorEngineError(f"Missing OHLCV for {ticker}")
    df = df.copy()
    df.attrs["ticker"] = ticker
    sector = pref_row.get("sector") or sector_map.get(ticker)
    outputs: dict[str, Any] = {
        "ticker": ticker,
        "date": today_et(),
        "regime": pref_row.get("regime"),
    }
    for module_name, module in MODULES:
        try:
            module_out = module.compute_factors(df, spy_df, vix_value, sector, universe_stats)
        except Exception as exc:
            _progress(f"WARNING: {ticker} failed in {module_name}: {exc}")
            module_out = _module_nan_dict(module_name, active_by_module)
        outputs.update(module_out)
    return outputs


def _ensure_factor_matrix_table(con: sqlite3.Connection, active_factors: list[str]) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_matrix_daily (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            regime TEXT,
            PRIMARY KEY (date, ticker)
        )
        """
    )
    existing = {
        row["name"]
        for row in con.execute("PRAGMA table_info(factor_matrix_daily)").fetchall()
    }
    for factor in active_factors:
        if factor not in existing:
            con.execute(f'ALTER TABLE factor_matrix_daily ADD COLUMN "{factor}" REAL')
    con.commit()


def _write_factor_matrix(con: sqlite3.Connection, frame: pd.DataFrame, active_factors: list[str]) -> int:
    _ensure_factor_matrix_table(con, active_factors)
    cols = ["date", "ticker", "regime", *active_factors]
    placeholders = ",".join("?" * len(cols))
    col_list = ", ".join(f'"{c}"' for c in cols)
    run_dates = sorted({str(v) for v in frame["date"].dropna().astype(str).unique()}) if "date" in frame.columns else []
    for run_date in run_dates:
        con.execute("DELETE FROM factor_matrix_daily WHERE date = ?", (run_date,))
    rows = []
    for _, row in frame[cols].iterrows():
        rows.append(tuple(row[col] if pd.notna(row[col]) else None for col in cols))
    con.executemany(
        f"INSERT OR REPLACE INTO factor_matrix_daily ({col_list}) VALUES ({placeholders})",
        rows,
    )
    con.commit()
    return len(rows)


def _set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO cache_meta (key, value, updated_at)
        VALUES (?, ?, ?)
        """,
        (key, value, now_et_iso()),
    )


def _load_cached_prefilter_results(
    con: sqlite3.Connection,
    *,
    cache_date: str | None = None,
    latest: bool = False,
) -> pd.DataFrame:
    if not _table_exists(con, "prefilter_results"):
        return pd.DataFrame()
    target_date = cache_date
    if latest and target_date is None:
        row = con.execute("SELECT MAX(date) AS max_date FROM prefilter_results").fetchone()
        target_date = str(row["max_date"]) if row and row["max_date"] is not None else None
    if not target_date:
        return pd.DataFrame()
    frame = pd.read_sql_query(
        """
        SELECT ticker, regime, price, dollar_volume, bars_available, atr_pct, adx, sector
        FROM prefilter_results
        WHERE date = ?
        ORDER BY ticker ASC
        """,
        con,
        params=(target_date,),
    )
    if frame.empty:
        return frame
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    frame.attrs["cache_date"] = target_date
    frame.attrs["source"] = "prefilter_cache"
    return frame


def _resolve_prefilter_frame(
    db_path: Path,
    *,
    use_prefilter_cache: bool,
    skip_prefilter: bool,
) -> pd.DataFrame:
    today = today_et()
    con = _connect_db(db_path)
    try:
        prefilter_run_at = _get_meta(con, "prefilter_run_at")
        cache_fresh = bool(prefilter_run_at and str(prefilter_run_at)[:10] == today)
        if skip_prefilter:
            cached = _load_cached_prefilter_results(con, latest=True)
            if cached.empty:
                raise FactorEngineError(
                    "--skip-prefilter requested but no cached prefilter_results are available"
                )
            cache_date = str(cached.attrs.get("cache_date", "unknown"))
            freshness = "fresh" if cache_date == today else "stale"
            _progress(f"Using cached Stage 2 prefilter ({freshness}, date={cache_date})")
            return cached
        if use_prefilter_cache and cache_fresh:
            cached = _load_cached_prefilter_results(con, cache_date=today)
            if not cached.empty:
                _progress(f"Using cached Stage 2 prefilter for {today} ({len(cached)} survivors)")
                return cached
    finally:
        con.close()

    _progress("Running Stage 2 prefilter...")
    prefilter_t0 = time.time()
    prefiltered = run_prefilter(db_path)
    _progress(f"Prefilter complete in {time.time() - prefilter_t0:.1f}s")
    return prefiltered


def run_engine(
    *,
    db_path: Path,
    workers: int = 8,
    dry_run: bool = False,
    debug_ticker: str | None = None,
    prefilter_cache: bool = True,
    skip_prefilter: bool = False,
) -> pd.DataFrame:
    engine_t0 = time.time()
    if not db_path.exists():
        raise FactorEngineError(f"v2_universe.db missing at {db_path}")
    registry = _load_registry()
    warnings, grouped = _validate_registry(registry)
    for warning in warnings:
        _progress(f"WARNING: {warning}")
    active_entries = _active_registry_entries(registry)
    active_factors = [entry["name"] for entry in active_entries]
    active_by_module: dict[str, list[str]] = {}
    for entry in active_entries:
        active_by_module.setdefault(str(entry["module"]), []).append(str(entry["name"]))

    _progress("Starting...")
    prefiltered = _resolve_prefilter_frame(
        db_path,
        use_prefilter_cache=prefilter_cache,
        skip_prefilter=skip_prefilter,
    )
    if prefiltered.empty:
        raise FactorEngineError("Prefilter DataFrame empty")
    tickers = sorted(prefiltered["ticker"].astype(str).str.upper().tolist())
    _progress(f"Starting: {len(tickers)} tickers, {len(active_factors)} active factors")

    con = _connect_db(db_path)
    try:
        spy_exists = con.execute("SELECT 1 FROM daily_bars WHERE ticker='SPY' LIMIT 1").fetchone()
    finally:
        con.close()
    if not spy_exists:
        raise FactorEngineError("SPY not in DB")

    tickers_to_load = sorted(set(tickers + ["SPY", "VIXY", "VXX"]))
    _progress("Pre-computing universe stats...")
    t0 = time.time()
    ohlcv_map = _load_ohlcv_map(db_path, tickers_to_load)
    if "SPY" not in ohlcv_map:
        raise FactorEngineError("SPY OHLCV missing")
    spy_df = ohlcv_map["SPY"].copy()
    vix_history, vix_value = _pick_vix_history(ohlcv_map)
    sector_map = _load_sector_map()
    options_map = _load_options_map(db_path, tickers)
    universe_stats = compute_universe_stats(ohlcv_map, spy_df, vix_history, sector_map, options_map)
    _progress(
        "Universe stats: breadth="
        f"{universe_stats['market_breadth']:.2f}, "
        f"A/D={universe_stats['advance_decline_ratio']:.2f}, "
        f"VIX_pct={universe_stats['vix_252d_percentile']:.2f}"
    )
    _progress(f"Loading OHLCV for {len(tickers)} survivors...")
    _progress(f"OHLCV loaded: {len([t for t in tickers if t in ohlcv_map])} tickers in {time.time() - t0:.1f}s")

    pref_map = {str(row["ticker"]).upper(): row.to_dict() for _, row in prefiltered.iterrows()}
    if debug_ticker:
        debug_ticker = debug_ticker.upper()
        if debug_ticker not in ohlcv_map:
            raise FactorEngineError(f"Debug ticker {debug_ticker} missing from DB")
        debug_row = pref_map.get(debug_ticker, {"ticker": debug_ticker, "regime": "UNKNOWN", "sector": sector_map.get(debug_ticker)})
        row = _process_ticker(debug_ticker, debug_row, ohlcv_map, spy_df, vix_value, universe_stats, sector_map, active_by_module)
        _progress(f"Debug mode: {debug_ticker}")
        for module_name, module in MODULES:
            _progress(f"--- Module {module_name} ---")
            for name in active_by_module.get(module_name, []):
                _progress(f"{name}: {row.get(name)}")
        active_values = [name for name in active_factors if pd.isna(row.get(name))]
        _progress("--- Summary ---")
        _progress(f"Total factors: {len(active_factors)}")
        _progress(f"NaN count: {len(active_values)}" + (f" ({', '.join(active_values)})" if active_values else ""))
        return pd.DataFrame([row])

    _progress("Computing factors...")
    rows: list[dict[str, Any]] = []
    total = len(tickers)
    all_nan_vectors = 0
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        futures = {
            ex.submit(
                _process_ticker,
                ticker,
                pref_map[ticker],
                ohlcv_map,
                spy_df,
                vix_value,
                universe_stats,
                sector_map,
                active_by_module,
            ): ticker
            for ticker in tickers
        }
        done = 0
        for fut in as_completed(futures):
            row = fut.result()
            done += 1
            if done % 500 == 0 or done == total:
                pct = int((done / max(total, 1)) * 100)
                _progress(f"Progress: {done}/{total} ({pct}%)...")
            active_values = [row.get(name) for name in active_factors]
            if all(pd.isna(v) for v in active_values):
                all_nan_vectors += 1
            rows.append(row)

    if total and (all_nan_vectors / total) > 0.50:
        raise FactorEngineError("> 50% of tickers produced all-NaN factor vectors")

    frame = pd.DataFrame(rows)
    frame = frame[["ticker", "date", "regime", *active_factors]].sort_values(["ticker"]).reset_index(drop=True)
    nan_rate = float(frame[active_factors].isna().sum().sum() / (len(frame) * len(active_factors))) if len(frame) and active_factors else 0.0
    _progress("Factor NaN rates (>5% only):")
    for factor in active_factors:
        nan_count = int(frame[factor].isna().sum())
        pct = (nan_count / len(frame)) * 100 if len(frame) else 0.0
        if pct > 5.0:
            _progress(f"  {factor}: {pct:.1f}% NaN ({nan_count}/{len(frame)})")

    if dry_run:
        return frame

    con = _connect_db(db_path)
    try:
        written = _write_factor_matrix(con, frame, active_factors)
        _set_meta(con, "factor_engine_run_at", now_utc_iso())
        _set_meta(con, "factor_engine_tickers", str(len(frame)))
        _set_meta(con, "factor_engine_nan_rate", f"{nan_rate:.6f}")
        _set_meta(con, "factor_engine_elapsed_seconds", f"{time.time() - engine_t0:.3f}")
        con.commit()
    finally:
        con.close()
    elapsed = time.time() - engine_t0
    _progress(f"DONE: {len(frame)} tickers × {len(active_factors)} factors in {elapsed:.1f}s")
    _progress("Written to factor_matrix_daily table")
    return frame


def compute_factors(db_or_con: sqlite3.Connection | Path | str, target_date: str | None = None) -> pd.DataFrame:
    """Compatibility helper for QA/UAT scripts.

    Returns stored factor_matrix_daily rows for the requested date when available.
    If the requested date is absent, falls back to the latest available factor date.
    """
    external_con = isinstance(db_or_con, sqlite3.Connection)
    con = db_or_con if external_con else _connect_db(Path(db_or_con).expanduser().resolve())
    try:
        if not _table_exists(con, "factor_matrix_daily"):
            raise FactorEngineError("factor_matrix_daily table missing")
        run_date: str | None = None
        if target_date:
            row = con.execute(
                "SELECT MAX(date) AS d FROM factor_matrix_daily WHERE date <= ?",
                (target_date,),
            ).fetchone()
            run_date = str(row[0]) if row and row[0] is not None else None
        if not run_date:
            row = con.execute("SELECT MAX(date) AS d FROM factor_matrix_daily").fetchone()
            run_date = str(row[0]) if row and row[0] is not None else None
        if not run_date:
            raise FactorEngineError("factor_matrix_daily is empty")
        frame = pd.read_sql_query(
            "SELECT * FROM factor_matrix_daily WHERE date = ? ORDER BY ticker ASC",
            con,
            params=(run_date,),
        )
        frame.attrs["date"] = run_date
        return frame
    finally:
        if not external_con:
            con.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meridian Stage 3 factor engine")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug", default=None)
    parser.add_argument("--prefilter-cache", dest="prefilter_cache", action="store_true", default=True)
    parser.add_argument("--no-prefilter-cache", dest="prefilter_cache", action="store_false")
    parser.add_argument("--skip-prefilter", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    t0 = time.time()
    try:
        frame = run_engine(
            db_path=Path(args.db).expanduser().resolve(),
            workers=args.workers,
            dry_run=args.dry_run,
            debug_ticker=args.debug,
            prefilter_cache=args.prefilter_cache,
            skip_prefilter=args.skip_prefilter,
        )
    except (FactorEngineError, PrefilterError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    elapsed = time.time() - t0
    print(
        json.dumps(
            {
                "ok": True,
                "rows": len(frame),
                "columns": list(frame.columns),
                "elapsed_s": round(elapsed, 1),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
