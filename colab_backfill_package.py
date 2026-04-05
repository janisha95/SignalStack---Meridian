#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import py_compile
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import zipfile
from pathlib import Path

import pandas as pd


STAGE_NAME = "colab_pkg"
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "v2_universe.db"
ZIP_PATH = ROOT / "colab_backfill.zip"
FACTOR_ENGINE_PATH = ROOT / "stages" / "v2_factor_engine.py"
FACTOR_DIR = ROOT / "stages" / "factors"
REGISTRY_PATH = ROOT / "config" / "factor_registry.json"
SECTOR_MAP_PATH = ROOT / "config" / "ticker_sector_map.json"


def _progress(message: str) -> None:
    print(f"[{STAGE_NAME}] {message}", flush=True)


def _connect_db(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _package_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="colab_backfill_"))


def _copy_support_files(package_dir: Path) -> None:
    stages_dir = package_dir / "stages"
    factors_out = stages_dir / "factors"
    config_dir = package_dir / "config"
    stages_dir.mkdir(parents=True, exist_ok=True)
    factors_out.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    (stages_dir / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(FACTOR_ENGINE_PATH, stages_dir / "v2_factor_engine.py")
    for path in sorted(FACTOR_DIR.glob("*.py")):
        shutil.copy2(path, factors_out / path.name)
    shutil.copy2(REGISTRY_PATH, config_dir / "factor_registry.json")
    shutil.copy2(SECTOR_MAP_PATH, config_dir / "ticker_sector_map.json")

    # Stub only to satisfy v2_factor_engine imports inside the package.
    (stages_dir / "v2_prefilter.py").write_text(
        textwrap.dedent(
            """
            class PrefilterError(RuntimeError):
                pass

            def run_prefilter(*args, **kwargs):
                raise PrefilterError("run_prefilter is not available in the Colab backfill package")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _export_daily_bars_chunks(package_dir: Path, chunk_rows: int = 500_000) -> list[Path]:
    _progress("Exporting daily_bars to CSV chunks...")
    con = _connect_db(DB_PATH)
    out_paths: list[Path] = []
    total_rows = 0
    t0 = time.time()
    try:
        query = """
            SELECT ticker, date, open, high, low, close, volume
            FROM daily_bars
            ORDER BY ticker ASC, date ASC
        """
        for idx, chunk in enumerate(pd.read_sql_query(query, con, chunksize=chunk_rows), start=1):
            out_path = package_dir / f"daily_bars_part_{idx:03d}.csv"
            chunk.to_csv(out_path, index=False)
            out_paths.append(out_path)
            total_rows += len(chunk)
            _progress(
                f"CSV chunk {idx}: {len(chunk):,} rows "
                f"(cumulative {total_rows:,}, {time.time() - t0:.1f}s)"
            )
    finally:
        con.close()
    _progress(f"daily_bars export complete: {total_rows:,} rows across {len(out_paths)} files")
    return out_paths


def _colab_backfill_source() -> str:
    return textwrap.dedent(
        r'''
        #!/usr/bin/env python3
        from __future__ import annotations

        import argparse
        import json
        import sys
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from datetime import datetime, timezone
        from pathlib import Path
        from typing import Any

        import pandas as pd

        ROOT = Path(__file__).resolve().parent
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))

        from stages import v2_factor_engine as factor_engine
        from stages.factors import nan_dict


        STAGE_NAME = "colab_backfill"
        FORWARD_HORIZON = 5
        MIN_PRICE = 1.0
        MIN_DOLLAR_VOLUME = 500_000.0
        MIN_BARS = 50
        MIN_WARMUP_DAYS = 100
        MIN_COMPUTED_ROWS = 100
        EXCLUDED_TICKERS = {"SPY", "VIXY", "VXX"}


        def _progress(message: str) -> None:
            print(f"[{STAGE_NAME}] {message}", flush=True)


        def _generated_at_utc() -> str:
            return datetime.now(timezone.utc).isoformat()


        def _load_registry() -> dict[str, Any]:
            path = ROOT / "config" / "factor_registry.json"
            return json.loads(path.read_text(encoding="utf-8"))


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


        def _load_sector_map() -> dict[str, str]:
            path = ROOT / "config" / "ticker_sector_map.json"
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(k).upper(): str(v) for k, v in data.items()}


        def _load_all_ohlcv() -> dict[str, pd.DataFrame]:
            _progress("Loading OHLCV CSV chunks...")
            t0 = time.time()
            parts = sorted(ROOT.glob("daily_bars_part_*.csv"))
            if not parts:
                raise RuntimeError("No daily_bars_part_*.csv files found")
            frames = []
            for idx, path in enumerate(parts, start=1):
                frames.append(pd.read_csv(path))
                _progress(f"Loaded CSV part {idx}/{len(parts)}: {path.name}")
            frame = pd.concat(frames, ignore_index=True)
            if frame.empty:
                raise RuntimeError("daily_bars CSV is empty")
            for col in ("open", "high", "low", "close", "volume"):
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
            frame["ticker"] = frame["ticker"].astype(str).str.upper()
            frame["date"] = frame["date"].astype(str)
            out: dict[str, pd.DataFrame] = {}
            for ticker, ticker_frame in frame.groupby("ticker", sort=False):
                df = ticker_frame.reset_index(drop=True)
                df.attrs["ticker"] = str(ticker).upper()
                out[str(ticker).upper()] = df
            _progress(f"Loaded {len(out)} tickers, {len(frame):,} bars in {time.time() - t0:.1f}s")
            return out


        def _slice_up_to_date(df: pd.DataFrame, current_date: str) -> pd.DataFrame:
            idx = df["date"].searchsorted(current_date, side="right")
            sliced = df.iloc[:idx]
            sliced.attrs["ticker"] = df.attrs.get("ticker")
            return sliced


        def compute_forward_return(all_ohlcv: dict[str, pd.DataFrame], ticker: str, current_date: str, horizon: int = FORWARD_HORIZON) -> float:
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


        def _wilder_smooth(values: list[float], period: int) -> list[float]:
            if len(values) < period:
                return []
            first = sum(values[:period])
            out = [first]
            for value in values[period:]:
                out.append(out[-1] - (out[-1] / period) + value)
            return out


        def _compute_adx_atr(highs: list[float], lows: list[float], closes: list[float]) -> tuple[float, float, bool]:
            if len(highs) < 2 or not closes or closes[-1] <= 0:
                return 0.0, 0.0, False
            tr_vals, plus_dm, minus_dm = [], [], []
            for i in range(1, len(highs)):
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

            atr_period = 14
            smoothed_tr = _wilder_smooth(tr_vals, atr_period)
            if not smoothed_tr:
                return 0.0, 0.0, False
            atr_series = [value / atr_period for value in smoothed_tr]
            latest_atr = atr_series[-1]
            atr_pct = latest_atr / closes[-1] if closes[-1] else 0.0
            atr_expansion = False
            if len(atr_series) >= 6:
                prev_window = atr_series[-6:-1]
                atr_expansion = latest_atr > (sum(prev_window) / len(prev_window))

            if len(highs) < 28:
                return 0.0, atr_pct, atr_expansion

            smoothed_plus = _wilder_smooth(plus_dm, atr_period)
            smoothed_minus = _wilder_smooth(minus_dm, atr_period)
            dx_vals = []
            for tr, p_dm, m_dm in zip(smoothed_tr, smoothed_plus, smoothed_minus):
                if tr <= 0:
                    dx_vals.append(0.0)
                    continue
                plus_di = 100.0 * p_dm / tr
                minus_di = 100.0 * m_dm / tr
                denom = plus_di + minus_di
                dx_vals.append(0.0 if denom <= 0 else 100.0 * abs(plus_di - minus_di) / denom)
            adx_smoothed = _wilder_smooth(dx_vals, atr_period)
            adx = adx_smoothed[-1] / atr_period if adx_smoothed else 0.0
            return adx, atr_pct, atr_expansion


        def _classify_regime(adx: float, atr_expansion: bool) -> str:
            if adx >= 25:
                return "TRENDING"
            if adx >= 15:
                return "CHOPPY"
            if atr_expansion:
                return "VOLATILE"
            return "UNKNOWN"


        def _compute_regime(df: pd.DataFrame) -> str:
            highs = pd.to_numeric(df["high"], errors="coerce").dropna().tolist()
            lows = pd.to_numeric(df["low"], errors="coerce").dropna().tolist()
            closes = pd.to_numeric(df["close"], errors="coerce").dropna().tolist()
            adx, _atr_pct, atr_expansion = _compute_adx_atr(highs, lows, closes)
            return _classify_regime(adx, atr_expansion)


        def _module_nan_dict(module_name: str, active_by_module: dict[str, list[str]]) -> dict[str, float]:
            return nan_dict(active_by_module.get(module_name, []))


        def _historical_prefilter(all_ohlcv: dict[str, pd.DataFrame], current_date: str, sector_map: dict[str, str]) -> tuple[list[str], dict[str, dict[str, Any]]]:
            survivors: list[str] = []
            meta: dict[str, dict[str, Any]] = {}
            for ticker, df in all_ohlcv.items():
                if ticker in EXCLUDED_TICKERS:
                    continue
                sliced = _slice_up_to_date(df, current_date)
                bars_available = len(sliced)
                if bars_available < MIN_BARS:
                    continue
                latest_close = float(sliced["close"].iloc[-1])
                if latest_close < MIN_PRICE:
                    continue
                dollar_volume = float((sliced["close"] * sliced["volume"]).tail(20).mean())
                if pd.isna(dollar_volume) or dollar_volume < MIN_DOLLAR_VOLUME:
                    continue
                survivors.append(ticker)
                meta[ticker] = {
                    "price": latest_close,
                    "dollar_volume": dollar_volume,
                    "bars_available": bars_available,
                    "sector": sector_map.get(ticker),
                }
            return sorted(survivors), meta


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
                raise RuntimeError(f"Missing OHLCV snapshot for {ticker} on {current_date}")
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


        def _compute_date_frame(
            current_date: str,
            survivors: list[str],
            meta_map: dict[str, dict[str, Any]],
            all_ohlcv: dict[str, pd.DataFrame],
            sector_map: dict[str, str],
            active_factor_names: list[str],
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
                raise RuntimeError(f"SPY snapshot missing on {current_date}")

            vix_history, vix_value = factor_engine._pick_vix_history(snapshot_map)
            universe_stats = factor_engine.compute_universe_stats(
                snapshot_map,
                spy_df,
                vix_history,
                sector_map,
                {},
            )

            rows = []
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
                return pd.DataFrame(columns=["date", "ticker", *active_factor_names, "forward_return_5d", "regime", "sector", "price"])

            frame = pd.DataFrame(rows)
            needed_cols = ["date", "ticker", *active_factor_names, "forward_return_5d", "regime", "sector", "price"]
            for col in needed_cols:
                if col not in frame.columns:
                    frame[col] = pd.NA
            return frame[needed_cols].sort_values(["ticker"]).reset_index(drop=True)


        def _write_batch(path: Path, frame: pd.DataFrame, append: bool) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, mode="a" if append else "w", header=not append, index=False)


        def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
            p = argparse.ArgumentParser(description="Colab training-data backfill")
            p.add_argument("--start-date", default=None)
            p.add_argument("--end-date", default=None)
            p.add_argument("--workers", type=int, default=8)
            p.add_argument("--save-every", type=int, default=100)
            p.add_argument("--output", default="training_data_colab.csv")
            return p.parse_args(argv)


        def main(argv: list[str] | None = None) -> int:
            args = parse_args(argv)
            active_factor_names = _active_factor_names()
            active_by_module = _active_by_module()
            sector_map = _load_sector_map()
            all_ohlcv = _load_all_ohlcv()

            spy_df = all_ohlcv.get("SPY")
            if spy_df is None or spy_df.empty:
                raise RuntimeError("SPY missing from OHLCV data")

            spy_days = sorted(spy_df["date"].astype(str).unique().tolist())
            if len(spy_days) <= FORWARD_HORIZON:
                raise RuntimeError("SPY does not have enough bars for forward returns")
            if len(spy_days) <= MIN_WARMUP_DAYS + FORWARD_HORIZON:
                raise RuntimeError("SPY does not have enough bars for warmup + forward returns")
            earliest_eligible = spy_days[MIN_WARMUP_DAYS]
            last_eligible = spy_days[-(FORWARD_HORIZON + 1)]
            target_start = max(args.start_date or earliest_eligible, earliest_eligible)
            target_end = min(args.end_date or last_eligible, last_eligible)
            trading_days = [d for d in spy_days if target_start <= d <= target_end]
            if not trading_days:
                raise RuntimeError("No trading days in requested range")

            _progress(
                f"Date range: {trading_days[0]} to {trading_days[-1]} ({len(trading_days)} trading days)"
            )
            output_path = ROOT / args.output
            if output_path.exists():
                output_path.unlink()
            checkpoint_path = ROOT / "training_data_colab_partial.csv"
            if checkpoint_path.exists():
                checkpoint_path.unlink()

            processed_frames = []
            total_rows = 0
            first_ten_start = time.time()

            for idx, current_date in enumerate(trading_days, start=1):
                survivors, meta_map = _historical_prefilter(all_ohlcv, current_date, sector_map)
                if len(survivors) < 100:
                    _progress(f"Date {current_date}: skipped ({len(survivors)} survivors < 100)")
                    continue
                frame = _compute_date_frame(
                    current_date,
                    survivors,
                    meta_map,
                    all_ohlcv,
                    sector_map,
                    active_factor_names,
                    active_by_module,
                    args.workers,
                )
                if frame.empty:
                    _progress(f"Date {current_date}: empty after factor computation")
                    continue
                if len(frame) < MIN_COMPUTED_ROWS:
                    _progress(f"Date {current_date}: skipped ({len(frame)} computed rows < {MIN_COMPUTED_ROWS})")
                    continue
                processed_frames.append(frame)
                total_rows += len(frame)

                if idx % 10 == 0 or idx == len(trading_days):
                    pct = idx * 100 // len(trading_days)
                    _progress(f"Progress: {idx}/{len(trading_days)} dates ({pct}%), rows={total_rows:,}")
                    if idx == 10:
                        elapsed = time.time() - first_ten_start
                        est_total = elapsed / 10 * len(trading_days)
                        _progress(f"Estimated completion time: {est_total/60:.1f} min based on first 10 dates")

                if idx % args.save_every == 0:
                    batch = pd.concat(processed_frames, ignore_index=True)
                    _write_batch(output_path, batch, append=output_path.exists())
                    _write_batch(checkpoint_path, batch, append=checkpoint_path.exists())
                    _progress(f"Checkpoint saved at {idx} dates: {len(batch):,} rows")
                    processed_frames = []

            if processed_frames:
                batch = pd.concat(processed_frames, ignore_index=True)
                _write_batch(output_path, batch, append=output_path.exists())

            report = {
                "ok": True,
                "generated_at": _generated_at_utc(),
                "output": str(output_path.name),
                "trading_days_processed": len(trading_days),
                "rows_written": total_rows,
            }
            (ROOT / "backfill_report_colab.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            _progress(f"DONE: {total_rows:,} rows written to {output_path}")
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        '''
    ).strip() + "\n"


def _write_colab_script(package_dir: Path) -> Path:
    script_path = package_dir / "colab_backfill.py"
    script_path.write_text(_colab_backfill_source(), encoding="utf-8")
    py_compile.compile(str(script_path), doraise=True)
    _progress(f"colab_backfill.py written and compiled: {script_path}")
    return script_path


def _build_zip(package_dir: Path, zip_path: Path) -> None:
    _progress(f"Building zip: {zip_path}")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(package_dir))
    _progress(f"Zip complete: {zip_path} ({zip_path.stat().st_size / (1024*1024):.1f} MB)")


def _local_smoke_test(zip_path: Path, start_date: str, end_date: str) -> None:
    _progress("Running local smoke test from extracted zip...")
    smoke_dir = Path(tempfile.mkdtemp(prefix="colab_backfill_smoke_"))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(smoke_dir)
    cmd = [
        sys.executable,
        "colab_backfill.py",
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--workers",
        "4",
        "--save-every",
        "20",
    ]
    t0 = time.time()
    result = subprocess.run(cmd, cwd=smoke_dir, text=True, capture_output=True)
    elapsed = time.time() - t0
    if result.returncode != 0:
        raise RuntimeError(
            f"Smoke test failed in {elapsed:.1f}s\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    out_csv = smoke_dir / "training_data_colab.csv"
    if not out_csv.exists():
        raise RuntimeError("Smoke test passed but training_data_colab.csv missing")
    _progress(f"Smoke test passed in {elapsed:.1f}s")
    _progress(result.stdout.strip()[-1200:])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build a self-contained Colab backfill package")
    p.add_argument("--chunk-rows", type=int, default=500_000)
    p.add_argument("--smoke-start", default="2026-03-12")
    p.add_argument("--smoke-end", default="2026-03-18")
    p.add_argument("--skip-smoke", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _progress("Starting...")
    if not DB_PATH.exists():
        raise SystemExit(f"Missing DB: {DB_PATH}")

    package_dir = _package_root()
    _progress(f"Working dir: {package_dir}")
    _copy_support_files(package_dir)
    _export_daily_bars_chunks(package_dir, chunk_rows=args.chunk_rows)
    _write_colab_script(package_dir)
    _build_zip(package_dir, ZIP_PATH)

    if not args.skip_smoke:
        _local_smoke_test(ZIP_PATH, args.smoke_start, args.smoke_end)

    _progress("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
