#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stages import v2_factor_engine as factor_engine
from stages import v2_prefilter as prefilter
from stages.factors import nan_dict, now_et_iso


STAGE_NAME = "backfill"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "v2_universe.db"
REPORT_PATH = ROOT / "data" / "backfill_report.json"
REGISTRY_PATH = ROOT / "config" / "factor_registry.json"
DEFAULT_START_DATE = "2024-09-01"
FORWARD_HORIZON = 5
MIN_PRICE = 1.0
MIN_DOLLAR_VOLUME = 500_000.0
MIN_BARS = 50
MIN_FACTOR_BARS = 200
EXCLUDED_TICKERS = {"SPY", "VIXY", "VXX"}


class TrainingBackfillError(RuntimeError):
    pass


def _progress(message: str) -> None:
    print(f"[{STAGE_NAME}] {message}", flush=True)


def _generated_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise TrainingBackfillError(f"v2_universe.db missing at {db_path}")
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        raise TrainingBackfillError(f"factor_registry.json missing at {REGISTRY_PATH}")
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _active_factor_names() -> list[str]:
    registry = _load_registry()
    return [str(entry["name"]) for entry in registry.get("factors", []) if entry.get("active")]


def _active_by_module() -> dict[str, list[str]]:
    registry = _load_registry()
    grouped: dict[str, list[str]] = {}
    for entry in registry.get("factors", []):
        if not entry.get("active"):
            continue
        grouped.setdefault(str(entry["module"]), []).append(str(entry["name"]))
    return grouped


def _load_all_ohlcv(db_path: Path) -> dict[str, pd.DataFrame]:
    _progress("Loading all OHLCV...")
    t0 = time.time()
    con = _connect_db(db_path)
    try:
        frame = pd.read_sql_query(
            """
            SELECT ticker, date, open, high, low, close, volume
            FROM daily_bars
            ORDER BY ticker ASC, date ASC
            """,
            con,
        )
    finally:
        con.close()
    if frame.empty:
        raise TrainingBackfillError("daily_bars is empty")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    frame["date"] = frame["date"].astype(str)
    out: dict[str, pd.DataFrame] = {}
    for ticker, ticker_frame in frame.groupby("ticker", sort=False):
        df = ticker_frame.reset_index(drop=True)
        df.attrs["ticker"] = str(ticker).upper()
        out[str(ticker).upper()] = df
    _progress(
        f"Loaded {len(out)} tickers, {len(frame)} bars in {time.time() - t0:.1f}s"
    )
    return out


def _date_arrays(all_ohlcv: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    return {ticker: df["date"].tolist() for ticker, df in all_ohlcv.items()}


def _slice_up_to_date(df: pd.DataFrame, current_date: str) -> pd.DataFrame:
    idx = df["date"].searchsorted(current_date, side="right")
    sliced = df.iloc[:idx]
    sliced.attrs["ticker"] = df.attrs.get("ticker")
    return sliced


def compute_forward_return(
    all_ohlcv: dict[str, pd.DataFrame],
    ticker: str,
    current_date: str,
    horizon: int = FORWARD_HORIZON,
) -> float:
    df = all_ohlcv.get(ticker.upper())
    if df is None or df.empty:
        return float("nan")
    idx = int(df["date"].searchsorted(current_date, side="right")) - 1
    if idx < 0 or idx >= len(df):
        return float("nan")
    future_idx = idx + horizon
    if future_idx >= len(df):
        return float("nan")
    close_now = float(df["close"].iloc[idx])
    close_future = float(df["close"].iloc[future_idx])
    if close_now <= 0:
        return float("nan")
    return float((close_future / close_now) - 1.0)


def _historical_prefilter(
    all_ohlcv: dict[str, pd.DataFrame],
    current_date: str,
    *,
    allowed_tickers: set[str] | None,
    sector_map: dict[str, str],
    min_price: float = MIN_PRICE,
    min_dollar_volume: float = MIN_DOLLAR_VOLUME,
    min_bars: int = MIN_BARS,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    survivors: list[str] = []
    meta: dict[str, dict[str, Any]] = {}
    for ticker, df in all_ohlcv.items():
        if ticker in EXCLUDED_TICKERS:
            continue
        if allowed_tickers is not None and ticker not in allowed_tickers:
            continue
        if prefilter._suffix_excluded(ticker):
            continue
        sliced = _slice_up_to_date(df, current_date)
        bars_available = len(sliced)
        if bars_available < min_bars:
            continue
        close = sliced["close"].astype(float)
        volume = sliced["volume"].astype(float)
        latest_close = float(close.iloc[-1])
        if latest_close < min_price:
            continue
        dollar_volume = float((close * volume).tail(20).mean())
        if pd.isna(dollar_volume) or dollar_volume < min_dollar_volume:
            continue
        survivors.append(ticker)
        meta[ticker] = {
            "price": latest_close,
            "dollar_volume": dollar_volume,
            "bars_available": bars_available,
            "sector": sector_map.get(ticker),
        }
    return sorted(survivors), meta


def _module_nan_dict(module_name: str, active_by_module: dict[str, list[str]]) -> dict[str, float]:
    return nan_dict(active_by_module.get(module_name, []))


def _compute_factor_row(
    ticker: str,
    current_date: str,
    pref_row: dict[str, Any],
    snapshot_map: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    vix_value: float,
    universe_stats: dict[str, Any],
    sector_map: dict[str, str],
    active_by_module: dict[str, list[str]],
) -> dict[str, Any]:
    df = snapshot_map.get(ticker)
    if df is None or df.empty:
        raise TrainingBackfillError(f"Missing OHLCV snapshot for {ticker} on {current_date}")
    sector = pref_row.get("sector") or sector_map.get(ticker)
    outputs: dict[str, Any] = {
        "date": current_date,
        "ticker": ticker,
        "regime": pref_row.get("regime"),
        "sector": sector,
        "price": pref_row.get("price"),
    }
    for module_name, module in factor_engine.MODULES:
        try:
            module_out = module.compute_factors(df, spy_df, vix_value, sector, universe_stats)
        except Exception as exc:
            _progress(f"WARNING: {ticker} failed in {module_name}: {exc}")
            module_out = _module_nan_dict(module_name, active_by_module)
        outputs.update(module_out)
    return outputs


def _compute_regime(df: pd.DataFrame) -> str:
    highs = df["high"].astype(float).dropna().tolist()
    lows = df["low"].astype(float).dropna().tolist()
    closes = df["close"].astype(float).dropna().tolist()
    adx, _atr_pct, atr_expansion = prefilter._compute_adx_atr(highs, lows, closes)
    return prefilter.classify_regime(adx, atr_expansion)


def _ensure_training_table(con: sqlite3.Connection, active_factors: list[str]) -> None:
    # Build factor column fragment safely — avoids "near ',': syntax error"
    # when active_factors is empty or all columns already exist in the table.
    factor_col_fragment = (
        (",\n".join(f'"{name}" REAL' for name in active_factors) + ",\n")
        if active_factors
        else ""
    )
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS training_data (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            {factor_col_fragment}forward_return_5d REAL,
            regime TEXT,
            sector TEXT,
            price REAL,
            PRIMARY KEY (date, ticker)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_training_date ON training_data(date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_training_ticker ON training_data(ticker)")
    # Check existing columns BEFORE attempting any ALTER TABLE — prevents duplicate-column
    # errors when v2_fundamental_enrichment.py has already added columns to this table.
    existing = {row["name"] for row in con.execute("PRAGMA table_info(training_data)").fetchall()}
    for factor in active_factors:
        if factor not in existing:
            con.execute(f'ALTER TABLE training_data ADD COLUMN "{factor}" REAL')
    con.commit()


def _write_training_rows(con: sqlite3.Connection, frame: pd.DataFrame, active_factors: list[str]) -> int:
    _ensure_training_table(con, active_factors)
    cols = ["date", "ticker", *active_factors, "forward_return_5d", "regime", "sector", "price"]
    placeholders = ",".join("?" * len(cols))
    col_list = ", ".join(f'"{col}"' for col in cols)
    rows = []
    for _, row in frame[cols].iterrows():
        rows.append(tuple(row[col] if pd.notna(row[col]) else None for col in cols))
    con.executemany(
        f"INSERT OR REPLACE INTO training_data ({col_list}) VALUES ({placeholders})",
        rows,
    )
    con.commit()
    return len(rows)


def _choose_trading_days(spy_df: pd.DataFrame, start_date: str, end_date: str | None) -> list[str]:
    spy_days = sorted(spy_df["date"].astype(str).unique().tolist())
    if len(spy_days) <= FORWARD_HORIZON:
        raise TrainingBackfillError("SPY does not have enough bars for forward returns")
    last_eligible = spy_days[-(FORWARD_HORIZON + 1)]
    target_end = min(end_date or last_eligible, last_eligible)
    trading_days = [d for d in spy_days if start_date <= d <= target_end]
    return trading_days


def _select_tickers(
    all_ohlcv: dict[str, pd.DataFrame],
    *,
    tickers_arg: str | None,
    sample: int | None,
    debug_ticker: str | None,
) -> set[str] | None:
    if debug_ticker:
        return {debug_ticker.upper()}
    if tickers_arg:
        return {part.strip().upper() for part in tickers_arg.split(",") if part.strip()}
    if sample:
        universe = sorted(t for t in all_ohlcv if t not in EXCLUDED_TICKERS)
        rng = random.Random(42)
        chosen = universe if sample >= len(universe) else rng.sample(universe, sample)
        return set(chosen)
    return None


def _compute_date_frame(
    current_date: str,
    survivors: list[str],
    meta_map: dict[str, dict[str, Any]],
    all_ohlcv: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
    active_factors: list[str],
    active_by_module: dict[str, list[str]],
    workers: int,
) -> pd.DataFrame:
    snapshot_map: dict[str, pd.DataFrame] = {}
    for ticker in sorted(set(survivors + ["SPY", "VIXY", "VXX"])):
        df = all_ohlcv.get(ticker)
        if df is None:
            continue
        sliced = _slice_up_to_date(df, current_date)
        if not sliced.empty:
            sliced.attrs["ticker"] = ticker
            snapshot_map[ticker] = sliced
    spy_df = snapshot_map.get("SPY")
    if spy_df is None or spy_df.empty:
        raise TrainingBackfillError(f"SPY snapshot missing on {current_date}")
    vix_history, vix_value = factor_engine._pick_vix_history(snapshot_map)
    universe_stats = factor_engine.compute_universe_stats(
        snapshot_map,
        spy_df,
        vix_history,
        sector_map,
        {},
    )
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        futures = {}
        for ticker in survivors:
            pref_row = dict(meta_map[ticker])
            pref_row["regime"] = _compute_regime(snapshot_map[ticker])
            futures[
                ex.submit(
                    _compute_factor_row,
                    ticker,
                    current_date,
                    pref_row,
                    snapshot_map,
                    spy_df,
                    vix_value,
                    universe_stats,
                    sector_map,
                    active_by_module,
                )
            ] = ticker
        for fut in as_completed(futures):
            ticker = futures[fut]
            row = fut.result()
            row["forward_return_5d"] = compute_forward_return(all_ohlcv, ticker, current_date, FORWARD_HORIZON)
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["date", "ticker", *active_factors, "forward_return_5d", "regime", "sector", "price"])
    frame = pd.DataFrame(rows)
    needed_cols = ["date", "ticker", *active_factors, "forward_return_5d", "regime", "sector", "price"]
    for col in needed_cols:
        if col not in frame.columns:
            frame[col] = pd.NA
    return frame[needed_cols].sort_values(["ticker"]).reset_index(drop=True)


def _validate_dataset_shape(
    all_ohlcv: dict[str, pd.DataFrame],
    trading_days: list[str],
    *,
    start_date: str,
    end_date: str | None,
    dry_run: bool,
    sample: int | None,
    tickers_arg: str | None,
    debug_ticker: str | None,
) -> None:
    targeted_range = bool(end_date) and start_date == end_date
    strict = (
        not dry_run
        and sample is None
        and tickers_arg is None
        and debug_ticker is None
        and not targeted_range
    )
    if strict and len(trading_days) < 100:
        raise TrainingBackfillError(f"Only {len(trading_days)} trading days in range")
    if strict:
        rich = sum(
            1
            for ticker, df in all_ohlcv.items()
            if ticker not in EXCLUDED_TICKERS and len(df) >= MIN_FACTOR_BARS
        )
        if rich < 500:
            raise TrainingBackfillError(f"Only {rich} tickers have {MIN_FACTOR_BARS}+ bars")


def _nan_rate_summary(frame: pd.DataFrame, active_factors: list[str]) -> dict[str, float]:
    if frame.empty:
        return {factor: 1.0 for factor in active_factors}
    return {
        factor: float(frame[factor].isna().sum() / len(frame))
        for factor in active_factors
    }


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def run_backfill(
    *,
    db_path: Path,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    tickers: str | None = None,
    sample: int | None = None,
    workers: int = 4,
    batch_days: int = 20,
    dry_run: bool = False,
    debug_ticker: str | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    active_factors = factor_engine._active_registry_entries(_load_registry())
    active_factor_names = [str(entry["name"]) for entry in active_factors]
    active_by_module = _active_by_module()
    # Auto-detect full date range from daily_bars when using the hardcoded default.
    # This picks up extended history (e.g. 2020-01 to present) without requiring
    # a CLI flag change when new data is downloaded.
    if start_date == DEFAULT_START_DATE:
        _con_dates = _connect_db(db_path)
        try:
            _row = _con_dates.execute(
                "SELECT MIN(date), MAX(date) FROM daily_bars"
            ).fetchone()
            _db_min, _db_max = _row[0], _row[1]
        finally:
            _con_dates.close()
        if _db_min:
            start_date = str(_db_min)
            _progress(f"Auto-detected start_date from daily_bars: {start_date}")
        if end_date is None and _db_max:
            end_date = str(_db_max)
            _progress(f"Auto-detected end_date from daily_bars: {end_date}")
    all_ohlcv = _load_all_ohlcv(db_path)
    spy_df = all_ohlcv.get("SPY")
    if spy_df is None or spy_df.empty:
        raise TrainingBackfillError("SPY missing from DB")
    trading_days = _choose_trading_days(spy_df, start_date, end_date)
    _validate_dataset_shape(
        all_ohlcv,
        trading_days,
        start_date=start_date,
        end_date=end_date,
        dry_run=dry_run,
        sample=sample,
        tickers_arg=tickers,
        debug_ticker=debug_ticker,
    )
    selected_tickers = _select_tickers(
        all_ohlcv,
        tickers_arg=tickers,
        sample=sample,
        debug_ticker=debug_ticker,
    )
    sector_map = factor_engine._load_sector_map()
    _progress(
        f"Date range: {trading_days[0]} to {trading_days[-1]} ({len(trading_days)} trading days)"
    )

    if dry_run:
        trading_days = trading_days[:1]

    total_rows_written = 0
    batch_frames: list[pd.DataFrame] = []
    all_frames: list[pd.DataFrame] = []
    date_counts: list[int] = []
    nan_rates_accum: dict[str, int] = {factor: 0 for factor in active_factor_names}
    debug_target = debug_ticker.upper() if debug_ticker else None

    con = None if dry_run else _connect_db(db_path)
    try:
        if con is not None:
            _ensure_training_table(con, active_factor_names)
        for idx, current_date in enumerate(trading_days, start=1):
            survivors, meta_map = _historical_prefilter(
                all_ohlcv,
                current_date,
                allowed_tickers=selected_tickers,
                sector_map=sector_map,
            )
            if not survivors:
                _progress(
                    f"Date {current_date}: 0 tickers ({idx}/{len(trading_days)}, {idx*100//len(trading_days)}%)"
                )
                if dry_run:
                    continue
                continue
            if len(survivors) < 1500 and selected_tickers is None and not debug_target:
                _progress(f"WARNING: low survivor count on {current_date}: {len(survivors)}")
            frame = _compute_date_frame(
                current_date,
                survivors,
                meta_map,
                all_ohlcv,
                sector_map,
                active_factor_names,
                active_by_module,
                workers,
            )
            if frame.empty:
                _progress(
                    f"WARNING: {current_date}: 0 tickers after factor computation "
                    f"(warmup period? expected for early dates) — skipping"
                )
                continue
            if active_factor_names and frame[active_factor_names].isna().all(axis=1).all():
                _progress(
                    f"WARNING: {current_date}: all factor values are NaN "
                    f"(ticker warmup <{MIN_FACTOR_BARS} bars?) — skipping"
                )
                continue

            date_counts.append(len(frame))
            for factor in active_factor_names:
                nan_rates_accum[factor] += int(frame[factor].isna().sum())
            batch_frames.append(frame)
            all_frames.append(frame)
            _progress(
                f"Date {current_date}: {len(frame)} tickers ({idx}/{len(trading_days)}, {idx*100//len(trading_days)}%)"
            )

            if debug_target and debug_target in set(frame["ticker"]):
                debug_row = frame.loc[frame["ticker"] == debug_target].iloc[0]
                _progress(f"Debug mode: {debug_target} @ {current_date}")
                for module_name, _module in factor_engine.MODULES:
                    _progress(f"--- {module_name} ---")
                    for factor in active_by_module.get(module_name, []):
                        _progress(f"{factor}: {debug_row.get(factor)}")
                _progress("--- target ---")
                _progress(f"forward_return_5d: {debug_row.get('forward_return_5d')}")
                _progress(f"regime: {debug_row.get('regime')}")
                _progress(f"sector: {debug_row.get('sector')}")
                _progress(f"price: {debug_row.get('price')}")

            if con is not None and (idx % batch_days == 0 or idx == len(trading_days)):
                batch_frame = pd.concat(batch_frames, ignore_index=True)
                written = _write_training_rows(con, batch_frame, active_factor_names)
                total_rows_written += written
                _progress(f"Batch written: {written} rows")
                batch_frames = []
        combined = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=["date", "ticker", *active_factor_names, "forward_return_5d", "regime", "sector", "price"])
        total_rows = total_rows_written if not dry_run else len(combined)
        factor_nan_rates = {
            factor: (nan_rates_accum[factor] / max(len(combined), 1))
            for factor in active_factor_names
        }
        _progress("Factor NaN rates (>5% only):")
        for factor, rate in factor_nan_rates.items():
            if rate > 0.05:
                suffix = ""
                if factor in {"options_pcr", "options_unusual_vol"}:
                    suffix = " (expected — no historical options data)"
                _progress(
                    f"  {factor}: {rate * 100:.1f}% NaN ({nan_rates_accum[factor]}/{max(len(combined), 1)}){suffix}"
                )

        elapsed = time.time() - t0
        report = {
            "ok": True,
            "generated_at": _generated_at_utc(),
            "start_date": trading_days[0] if trading_days else start_date,
            "end_date": trading_days[-1] if trading_days else end_date,
            "trading_days_processed": len(trading_days),
            "total_rows_written": total_rows,
            "avg_tickers_per_date": round(sum(date_counts) / len(date_counts), 2) if date_counts else 0.0,
            "nan_rate_overall": float(
                combined[active_factor_names].isna().sum().sum() / max(len(combined) * len(active_factor_names), 1)
            ) if active_factor_names else 0.0,
            "forward_return_coverage": float(
                combined["forward_return_5d"].notna().mean()
            ) if not combined.empty else 0.0,
            "elapsed_seconds": round(elapsed, 1),
            "factor_nan_rates": {k: round(v, 4) for k, v in factor_nan_rates.items()},
        }
        if not dry_run:
            _write_report(report)
        _progress(
            f"DONE: {total_rows} rows, {len(trading_days)} days, {elapsed:.1f}s"
        )
        return {
            "frame": combined,
            "report": report,
        }
    finally:
        if con is not None:
            con.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meridian Stage 4A training data backfill")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--tickers", default=None)
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-days", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_backfill(
            db_path=Path(args.db).expanduser().resolve(),
            start_date=args.start_date,
            end_date=args.end_date,
            tickers=args.tickers,
            sample=args.sample,
            workers=args.workers,
            batch_days=args.batch_days,
            dry_run=args.dry_run,
            debug_ticker=args.debug,
        )
    except TrainingBackfillError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    frame = result["frame"]
    report = dict(result["report"])
    if args.dry_run:
        report["sample_rows"] = frame.head(10).to_dict(orient="records")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
