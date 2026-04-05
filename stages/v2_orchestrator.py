#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stages.factors import now_et, now_et_iso, now_utc_iso, today_et
from stages.v2_cache_warm import CacheWarmError, ValidationAbort, parse_args as parse_cache_args, run_pipeline as run_cache_pipeline
from stages.v2_factor_engine import FactorEngineError, run_engine
from stages.v2_prefilter import PrefilterError, run_prefilter
from stages.v2_risk_filters import RiskFilterError, build_tradeable_portfolio
from stages.v2_selection import SelectionError, _mock_predictions as generate_mock_predictions, select_shortlist
from stages.tcn_scorer import TCNScorer
from stages.v2_forward_tracker import ensure_table as _ft_ensure_table, snapshot_picks as _ft_snapshot


STAGE_NAME = "orchestrator"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "v2_universe.db"

# Union of tcn_pass_v1 + tcn_short_v1 features — all 26 must be in factor_history
ALL_TCN_FEATURES = [
    # tcn_pass_v1 (long model)
    "momentum_acceleration", "momentum_impulse", "volume_participation",
    "volume_flow_direction", "effort_vs_result", "volatility_rank",
    "volatility_acceleration", "wick_rejection", "bb_position",
    "ma_alignment", "dist_from_ma20_atr", "wyckoff_phase",
    "phase_confidence", "damage_depth", "rollover_strength",
    "rs_vs_spy_10d", "rs_vs_spy_20d", "rs_momentum", "directional_conviction",
    # tcn_short_v1 additional features
    "adx", "leadership_score", "setup_score", "volume_climax",
    "ma_death_cross_proximity", "downside_volume_dominance", "vix_regime",
]


class OrchestratorError(RuntimeError):
    pass


@dataclass
class StageOutcome:
    stage: str
    status: str
    elapsed_seconds: float
    detail: dict[str, Any]


def _progress(message: str) -> None:
    print(f"[{STAGE_NAME}] {message}", flush=True)


def _connect_db(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _ensure_meta_tables(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS cache_meta (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS orchestrator_log (
            date TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            elapsed_seconds REAL,
            detail TEXT,
            PRIMARY KEY (date, stage)
        );

        CREATE TABLE IF NOT EXISTS predictions_daily (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            tcn_long_score REAL,
            tcn_short_score REAL,
            regime TEXT,
            sector TEXT,
            price REAL,
            PRIMARY KEY (date, ticker)
        );

        CREATE TABLE IF NOT EXISTS factor_history (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            adx REAL,
            bb_position REAL,
            dist_from_ma20_atr REAL,
            rs_vs_spy_10d REAL,
            volume_participation REAL,
            momentum_acceleration REAL,
            volatility_rank REAL,
            wyckoff_phase REAL,
            ma_alignment REAL,
            leadership_score REAL,
            setup_score REAL,
            damage_depth REAL,
            volume_climax REAL,
            rs_vs_spy_20d REAL,
            ma_death_cross_proximity REAL,
            downside_volume_dominance REAL,
            phase_confidence REAL,
            directional_conviction REAL,
            vix_regime REAL,
            PRIMARY KEY (date, ticker)
        );

        CREATE INDEX IF NOT EXISTS idx_fh_date ON factor_history(date);
        """
    )
    pred_cols = {str(row["name"]) for row in con.execute("PRAGMA table_info(predictions_daily)").fetchall()}
    for col in ("tcn_long_score", "tcn_short_score"):
        if col not in pred_cols:
            con.execute(f"ALTER TABLE predictions_daily ADD COLUMN {col} REAL")
    con.commit()


def _set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO cache_meta (key, value, updated_at)
        VALUES (?, ?, ?)
        """,
        (key, value, now_utc_iso()),
    )


def _write_orchestrator_log(db_path: Path, outcomes: list[StageOutcome]) -> None:
    con = _connect_db(db_path)
    try:
        _ensure_meta_tables(con)
        run_date = today_et()
        for outcome in outcomes:
            con.execute(
                """
                INSERT OR REPLACE INTO orchestrator_log (
                    date, stage, status, elapsed_seconds, detail
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_date,
                    outcome.stage,
                    outcome.status,
                    round(outcome.elapsed_seconds, 3),
                    json.dumps(outcome.detail, sort_keys=True),
                ),
            )
        _set_meta(con, "orchestrator_run_at", now_utc_iso())
        overall = "OK" if all(o.status in {"OK", "SKIP", "MOCK"} for o in outcomes if o.stage in {"1", "2", "3"}) else "FAIL"
        _set_meta(con, "orchestrator_status", overall)
        _set_meta(con, "orchestrator_elapsed", f"{sum(o.elapsed_seconds for o in outcomes):.3f}")
        con.commit()
    finally:
        con.close()


def _load_latest_prefilter(db_path: Path) -> pd.DataFrame:
    con = _connect_db(db_path)
    try:
        _ensure_meta_tables(con)
        row = con.execute("SELECT MAX(date) AS d FROM prefilter_results").fetchone()
        run_date = str(row["d"]) if row and row["d"] is not None else None
        if not run_date:
            raise OrchestratorError("prefilter_results missing; run Stage 2 first")
        frame = pd.read_sql_query(
            """
            SELECT ticker, regime, price, dollar_volume, bars_available, atr_pct, adx, sector
            FROM prefilter_results
            WHERE date = ?
            ORDER BY ticker ASC
            """,
            con,
            params=(run_date,),
        )
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        return frame
    finally:
        con.close()


def _write_mock_predictions(db_path: Path, frame: pd.DataFrame) -> int:
    con = _connect_db(db_path)
    try:
        _ensure_meta_tables(con)
        run_date = today_et()
        rng = np.random.default_rng(42)
        rows = [
            (
                run_date,
                str(row["ticker"]).upper(),
                float(rng.uniform(0.3, 0.9)),
                float(rng.uniform(0.3, 0.9)),
                row["regime"] if pd.notna(row.get("regime")) else None,
                row["sector"] if pd.notna(row.get("sector")) else None,
                float(row["price"]) if pd.notna(row.get("price")) else None,
            )
            for _, row in frame.iterrows()
        ]
        con.execute("DELETE FROM predictions_daily WHERE date = ?", (run_date,))
        con.executemany(
            """
            INSERT OR REPLACE INTO predictions_daily (
                date, ticker, tcn_long_score, tcn_short_score,
                regime, sector, price
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        _set_meta(con, "ml_scoring_run_at", now_et_iso())
        _set_meta(con, "ml_scoring_mode", "MOCK")
        con.commit()
    finally:
        con.close()
    return len(frame)


def _write_predictions(db_path: Path, frame: pd.DataFrame, *, run_date: str, mode: str) -> int:
    con = _connect_db(db_path)
    try:
        _ensure_meta_tables(con)
        rows = [
            (
                run_date,
                str(row["ticker"]).upper(),
                float(row["tcn_long_score"]) if pd.notna(row.get("tcn_long_score")) else None,
                float(row["tcn_short_score"]) if pd.notna(row.get("tcn_short_score")) else None,
                row["regime"] if pd.notna(row.get("regime")) else None,
                row["sector"] if pd.notna(row.get("sector")) else None,
                float(row["price"]) if pd.notna(row.get("price")) else None,
            )
            for _, row in frame.iterrows()
        ]
        con.execute("DELETE FROM predictions_daily WHERE date = ?", (run_date,))
        con.executemany(
            """
            INSERT OR REPLACE INTO predictions_daily (
                date, ticker, tcn_long_score, tcn_short_score,
                regime, sector, price
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        _set_meta(con, "ml_scoring_run_at", now_et_iso())
        _set_meta(con, "ml_scoring_mode", mode)
        con.commit()
    finally:
        con.close()
    return len(frame)


def _write_factor_history(db_path: Path, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    con = _connect_db(db_path)
    try:
        _ensure_meta_tables(con)
        cols = ["date", "ticker", *[f for f in ALL_TCN_FEATURES if f in frame.columns]]
        for col in frame.columns:
            try:
                con.execute(f"ALTER TABLE factor_history ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:
                pass
        subset = frame[cols].copy()
        run_dates = sorted({str(v) for v in subset["date"].dropna().astype(str).unique()}) if "date" in subset.columns else []
        for run_date in run_dates:
            con.execute("DELETE FROM factor_history WHERE date = ?", (run_date,))
        rows = []
        for _, row in subset.iterrows():
            rows.append(tuple(row[col] if pd.notna(row[col]) else None for col in cols))
        placeholders = ",".join("?" * len(cols))
        col_list = ", ".join(cols)
        con.executemany(
            f"INSERT OR REPLACE INTO factor_history ({col_list}) VALUES ({placeholders})",
            rows,
        )
        con.commit()
        return len(rows)
    finally:
        con.close()


def _send_telegram_summary(message: str, *, no_telegram: bool) -> str:
    if no_telegram:
        _progress(f"Telegram skipped (--no-telegram)\n{message}")
        return "SKIP"
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        _progress(f"Telegram skipped (missing config)\n{message}")
        return "SKIP"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 300:
            raise OrchestratorError(f"Telegram send failed with status {resp.status}")
    return "OK"


def _format_summary(outcomes: dict[str, StageOutcome]) -> str:
    stage1 = outcomes.get("1")
    stage2 = outcomes.get("2")
    stage3 = outcomes.get("3")
    stage5 = outcomes.get("5")
    stage6 = outcomes.get("6")
    universe = stage2.detail.get("survivors", 0) if stage2 else 0
    factor_rows = stage3.detail.get("rows", 0) if stage3 else 0
    approved = stage6.detail.get("approved", 0) if stage6 else 0
    filtered = stage6.detail.get("rejected", 0) if stage6 else 0
    longs = stage5.detail.get("longs", 0) if stage5 else 0
    shorts = stage5.detail.get("shorts", 0) if stage5 else 0
    pipeline_status = "completed" if all(o.status in {"OK", "SKIP", "MOCK"} for o in outcomes.values()) else "degraded"
    total_elapsed = sum(o.elapsed_seconds for o in outcomes.values())
    return (
        f"Meridian Daily — {today_et()}\n\n"
        f"Pipeline: {pipeline_status} in {total_elapsed/60.0:.1f} min\n"
        f"Universe survivors: {universe}\n"
        f"Factor rows: {factor_rows}\n"
        f"Selection: {longs} LONG + {shorts} SHORT candidates\n"
        f"Risk: {approved} approved, {filtered} rejected\n"
        f"Stage 1: {stage1.status if stage1 else 'N/A'}"
    )


def _log_debug_prefilter(frame: pd.DataFrame, ticker: str) -> None:
    row = frame.loc[frame["ticker"].astype(str).str.upper() == ticker]
    if row.empty:
        _progress(f"[Stage 2] {ticker}: filtered out or missing")
        return
    rec = row.iloc[0]
    _progress(
        f"[Stage 2] {ticker}: PASS (price ${float(rec['price']):.2f}, "
        f"vol ${float(rec['dollar_volume'])/1_000_000:.1f}M, {int(rec['bars_available'])} bars, "
        f"regime {rec['regime']})"
    )


def _log_debug_factors(frame: pd.DataFrame, ticker: str) -> None:
    row = frame.loc[frame["ticker"].astype(str).str.upper() == ticker]
    if row.empty:
        _progress(f"[Stage 3] {ticker}: missing from factor matrix")
        return
    factor_count = len([c for c in frame.columns if c not in {"ticker", "date", "regime"}])
    _progress(f"[Stage 3] {ticker}: {factor_count} factors computed")


def _log_debug_ml(frame: pd.DataFrame, ticker: str) -> None:
    row = frame.loc[frame["ticker"].astype(str).str.upper() == ticker]
    if row.empty:
        _progress(f"[Stage 4] {ticker}: no TCN score")
        return
    rec = row.iloc[0]
    long_s = float(rec["tcn_long_score"]) if pd.notna(rec.get("tcn_long_score")) else None
    short_s = float(rec["tcn_short_score"]) if pd.notna(rec.get("tcn_short_score")) else None
    _progress(f"[Stage 4] {ticker}: tcn_long={long_s:.3f} tcn_short={short_s:.3f}")


def _log_debug_selection(frame: pd.DataFrame, ticker: str) -> None:
    row = frame.loc[frame["ticker"].astype(str).str.upper() == ticker]
    if row.empty:
        _progress(f"[Stage 5] {ticker}: not shown in candidate list")
        return
    rec = row.iloc[0]
    _progress(
        f"[Stage 5] {ticker}: residual_alpha = {float(rec['residual_alpha']):+.2%} "
        f"(beta {float(rec['beta']):.2f}, rank #{int(rec['rank'])} {rec['direction']})"
    )


def _log_debug_risk(frame: pd.DataFrame, ticker: str) -> None:
    row = frame.loc[frame["ticker"].astype(str).str.upper() == ticker]
    if row.empty:
        _progress(f"[Stage 6] {ticker}: not evaluated by risk")
        return
    rec = row.iloc[0]
    if rec["filter_status"] == "APPROVED":
        _progress(
            f"[Stage 6] {ticker}: APPROVED — {int(rec['shares'])} shares, stop ${float(rec['stop_price']):.2f}, "
            f"risk {float(rec['risk_pct']):.1f}%"
        )
    else:
        _progress(f"[Stage 6] {ticker}: REJECTED — {rec['filter_reason']}")


def _run_stage1(*, args: argparse.Namespace, db_path: Path) -> dict[str, Any]:
    cache_args = parse_cache_args([])
    cache_args.db = str(db_path)
    cache_args.dry_run = args.dry_run
    cache_args.skip_alpaca = False
    cache_args.skip_yf = False
    cache_args.skip_options = False
    cache_args.days = args.days
    cache_args.full_refresh = args.full_refresh
    return run_cache_pipeline(cache_args)


def _run_stage2(*, db_path: Path, args: argparse.Namespace) -> pd.DataFrame:
    return run_prefilter(db_path, dry_run=args.dry_run)


def _run_stage3(*, db_path: Path, args: argparse.Namespace) -> pd.DataFrame:
    return run_engine(
        db_path=db_path,
        dry_run=args.dry_run,
        debug_ticker=args.debug if str(args.stage) == "3" else None,
        prefilter_cache=False,
        skip_prefilter=False,
    )


def _run_stage4_mock(*, db_path: Path, prefilter_df: pd.DataFrame, dry_run: bool) -> pd.DataFrame:
    frame = generate_mock_predictions(db_path)
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    if not dry_run:
        _write_mock_predictions(db_path, frame)
    return frame


def _latest_factor_date(db_path: Path) -> str:
    con = _connect_db(db_path)
    try:
        row = con.execute("SELECT MAX(date) AS d FROM factor_matrix_daily").fetchone()
        run_date = str(row["d"]) if row and row["d"] else None
        if not run_date:
            raise OrchestratorError("factor_matrix_daily missing latest date for Stage 4 real scoring")
        return run_date
    finally:
        con.close()


def _load_prediction_context(db_path: Path, run_date: str) -> pd.DataFrame:
    con = _connect_db(db_path)
    try:
        context = pd.read_sql_query(
            """
            SELECT fm.ticker,
                   fm.regime,
                   pr.sector,
                   db.close AS price
            FROM factor_matrix_daily fm
            LEFT JOIN prefilter_results pr
              ON pr.date = fm.date AND pr.ticker = fm.ticker
            LEFT JOIN daily_bars db
              ON db.date = fm.date AND db.ticker = fm.ticker
            WHERE fm.date = ?
            ORDER BY fm.ticker ASC
            """,
            con,
            params=(run_date,),
        )
    finally:
        con.close()
    context["ticker"] = context["ticker"].astype(str).str.upper()
    return context


def _run_stage4_real(*, db_path: Path, dry_run: bool) -> pd.DataFrame:
    run_date = _latest_factor_date(db_path)

    long_scorer = TCNScorer(model_dir=str(ROOT / "models" / "tcn_pass_v1"), db_path=str(db_path))
    short_scorer = TCNScorer(model_dir=str(ROOT / "models" / "tcn_short_v1"), db_path=str(db_path))

    long_df = long_scorer.score(run_date)
    short_df = short_scorer.score(run_date)

    if long_df.empty and short_df.empty:
        raise OrchestratorError(f"Real Stage 4: both TCN scorers returned empty for {run_date}")

    long_df = long_df.rename(columns={"tcn_score": "tcn_long_score"})
    short_df = short_df.rename(columns={"tcn_score": "tcn_short_score"})

    if long_df.empty:
        score_df = short_df.copy()
        score_df["tcn_long_score"] = 0.5
    elif short_df.empty:
        score_df = long_df.copy()
        score_df["tcn_short_score"] = 0.5
    else:
        score_df = long_df.merge(short_df, on="ticker", how="outer")
        score_df["tcn_long_score"] = score_df["tcn_long_score"].fillna(0.5)
        score_df["tcn_short_score"] = score_df["tcn_short_score"].fillna(0.5)

    context_df = _load_prediction_context(db_path, run_date)
    merged = score_df.merge(context_df, on="ticker", how="left")

    if "SPY" not in set(merged["ticker"]):
        spy_ctx = context_df.loc[context_df["ticker"] == "SPY"].copy()
        if spy_ctx.empty:
            spy_ctx = pd.DataFrame([{"ticker": "SPY", "regime": None, "sector": None, "price": float("nan")}])
        spy_ctx["tcn_long_score"] = 0.5
        spy_ctx["tcn_short_score"] = 0.5
        merged = pd.concat([merged, spy_ctx], ignore_index=True)

    merged["ticker"] = merged["ticker"].astype(str).str.upper()
    merged = merged.sort_values("ticker").reset_index(drop=True)

    # In real-ml mode, persist predictions even during dry-run so Stage 5 can consume
    # the exact Stage 4 output without changing selection.py.
    _write_predictions(db_path, merged, run_date=run_date, mode="REAL_TCN")
    return merged


def _run_stage5(*, db_path: Path, args: argparse.Namespace, use_mock: bool) -> pd.DataFrame:
    return select_shortlist(
        db_path=db_path,
        top_n=30,
        min_residual=0.0,
        show_all=False,
        dry_run=args.dry_run,
        debug_ticker=args.debug if str(args.stage) == "5" else None,
        mock=use_mock,
    )


def _run_stage6(*, db_path: Path, args: argparse.Namespace, use_mock: bool) -> tuple[pd.DataFrame, dict[str, Any]]:
    return build_tradeable_portfolio(
        db_path=db_path,
        prop_firm=args.prop_firm,
        dry_run=args.dry_run,
        debug_ticker=args.debug if str(args.stage) == "6" else None,
        mock=use_mock,
    )


def _record(outcomes: list[StageOutcome], stage: str, status: str, elapsed: float, detail: dict[str, Any]) -> None:
    outcomes.append(StageOutcome(stage=stage, status=status, elapsed_seconds=elapsed, detail=detail))


def run_orchestrator(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    outcomes: list[StageOutcome] = []
    start = time.time()
    _progress(f"Starting Meridian pipeline — {now_et().strftime('%Y-%m-%d %H:%M %Z')}")
    if args.debug:
        _progress(f"Debug: tracing {args.debug.upper()} through all stages")

    prefilter_df: pd.DataFrame | None = None
    factor_df: pd.DataFrame | None = None
    prediction_df: pd.DataFrame | None = None
    shortlist_df: pd.DataFrame | None = None
    risk_df: pd.DataFrame | None = None
    risk_state: dict[str, Any] | None = None

    stage_arg = str(args.stage).lower()
    specific_stage = stage_arg if stage_arg != "all" else None

    def should_run(stage_num: str) -> bool:
        return specific_stage is None or specific_stage == stage_num

    try:
        if should_run("1"):
            if args.skip_cache:
                _progress("Stage 1: Cache warm... SKIP (--skip-cache)")
                _record(outcomes, "1", "SKIP", 0.0, {"reason": "--skip-cache"})
            else:
                _progress("Stage 1: Cache warm...")
                t0 = time.time()
                report = _run_stage1(args=args, db_path=db_path)
                if not report.get("ok"):
                    raise OrchestratorError(f"Stage 1 failed: {report}")
                elapsed = time.time() - t0
                detail = {"ok": True, "bars": report.get("summary", {}).get("alpaca_warm", {}).get("rows_written")}
                _progress(f"Stage 1: Cache warm... OK ({elapsed:.1f}s)")
                _record(outcomes, "1", "OK", elapsed, detail)
        elif args.skip_cache:
            _record(outcomes, "1", "SKIP", 0.0, {"reason": "--skip-cache"})

        if should_run("2"):
            _progress("Stage 2: Prefilter...")
            t0 = time.time()
            prefilter_df = _run_stage2(db_path=db_path, args=args)
            elapsed = time.time() - t0
            _progress(f"Stage 2: Prefilter... OK ({len(prefilter_df)} survivors, {elapsed:.1f}s)")
            _record(outcomes, "2", "OK", elapsed, {"survivors": len(prefilter_df)})
            if args.debug:
                _log_debug_prefilter(prefilter_df, args.debug.upper())

        if should_run("3"):
            _progress("Stage 3: Factor engine...")
            t0 = time.time()
            factor_df = _run_stage3(db_path=db_path, args=args)
            elapsed = time.time() - t0
            factor_count = len([c for c in factor_df.columns if c not in {"ticker", "date", "regime"}])
            _progress(f"Stage 3: Factor engine... OK ({len(factor_df)} × {factor_count}, {elapsed:.1f}s)")
            if not args.dry_run:
                fh_written = _write_factor_history(db_path, factor_df)
                _progress(f"Stage 4A: factor_history... OK ({fh_written} rows)")
            _record(outcomes, "3", "OK", elapsed, {"rows": len(factor_df), "factor_count": factor_count})
            if args.debug:
                _log_debug_factors(factor_df, args.debug.upper())

        if should_run("4"):
            _progress("Stage 4: ML scoring...")
            t0 = time.time()
            if args.real_ml:
                prediction_df = _run_stage4_real(db_path=db_path, dry_run=args.dry_run)
                mode = "REAL_TCN"
                status = "OK"
                msg = "Stage 4: ML scoring... OK (real TCN dual)"
            else:
                if prefilter_df is None:
                    prefilter_df = _load_latest_prefilter(db_path)
                prediction_df = _run_stage4_mock(db_path=db_path, prefilter_df=prefilter_df, dry_run=args.dry_run)
                mode = "mock"
                status = "MOCK"
                msg = "Stage 4: ML scoring... MOCK (no trained model)"
            elapsed = time.time() - t0
            _progress(msg)
            _record(
                outcomes,
                "4",
                status,
                elapsed,
                {
                    "rows": len(prediction_df),
                    "mode": mode,
                    "tcn_long_max": float(prediction_df["tcn_long_score"].max()) if not prediction_df.empty and "tcn_long_score" in prediction_df else None,
                    "tcn_short_max": float(prediction_df["tcn_short_score"].max()) if not prediction_df.empty and "tcn_short_score" in prediction_df else None,
                },
            )
            if args.debug:
                _log_debug_ml(prediction_df, args.debug.upper())

        if should_run("5"):
            _progress("Stage 5: Selection...")
            t0 = time.time()
            try:
                use_mock = (not args.real_ml) and bool(args.mock_ml) and args.dry_run
                shortlist_df = _run_stage5(db_path=db_path, args=args, use_mock=use_mock)
                elapsed = time.time() - t0
                longs = int((shortlist_df["direction"] == "LONG").sum())
                shorts = int((shortlist_df["direction"] == "SHORT").sum())
                _progress(f"Stage 5: Selection... OK ({longs} LONG + {shorts} SHORT, {elapsed:.1f}s)")
                _record(outcomes, "5", "OK", elapsed, {"rows": len(shortlist_df), "longs": longs, "shorts": shorts})
                if args.debug:
                    _log_debug_selection(shortlist_df, args.debug.upper())
                # Forward tracking: snapshot today's picks
                if not args.dry_run:
                    try:
                        _ft_ensure_table(db_path)
                        n_snapped = _ft_snapshot(db_path)
                        _progress(f"Stage 5T: Forward tracking snapshot... {n_snapped} picks recorded")
                    except Exception as ft_exc:
                        _progress(f"Stage 5T: Forward tracking snapshot... WARN ({ft_exc})")
            except Exception as exc:
                elapsed = time.time() - t0
                _progress(f"Stage 5: Selection... FAIL ({exc})")
                _record(outcomes, "5", "FAIL", elapsed, {"error": str(exc), "rows": 0})
                shortlist_df = pd.DataFrame()
                if specific_stage == "5":
                    raise OrchestratorError(f"Stage 5 failed: {exc}") from exc

        if should_run("6"):
            _progress(f"Stage 6: Risk filters... ({args.prop_firm.upper()})")
            t0 = time.time()
            try:
                if specific_stage is None and any(o.stage == "5" and o.status == "FAIL" for o in outcomes):
                    raise RiskFilterError("Selection unavailable; Stage 6 skipped")
                use_mock = (not args.real_ml) and bool(args.mock_ml) and args.dry_run
                risk_df, risk_state = _run_stage6(db_path=db_path, args=args, use_mock=use_mock)
                elapsed = time.time() - t0
                approved = int((risk_df["filter_status"] == "APPROVED").sum())
                rejected = int((risk_df["filter_status"] != "APPROVED").sum())
                _progress(f"Stage 6: Risk filters... OK ({approved} approved, {rejected} filtered, {elapsed:.1f}s)")
                _record(outcomes, "6", "OK", elapsed, {"approved": approved, "rejected": rejected})
                if args.debug:
                    _log_debug_risk(risk_df, args.debug.upper())
            except Exception as exc:
                elapsed = time.time() - t0
                _progress(f"Stage 6: Risk filters... FAIL ({exc})")
                _record(outcomes, "6", "FAIL", elapsed, {"error": str(exc)})
                if specific_stage == "6":
                    raise OrchestratorError(f"Stage 6 failed: {exc}") from exc

    except (CacheWarmError, ValidationAbort, PrefilterError, FactorEngineError, OrchestratorError, sqlite3.OperationalError) as exc:
        elapsed = time.time() - start
        _progress(f"ABORT: {exc}")
        result = {
            "ok": False,
            "error": str(exc),
            "elapsed_s": round(elapsed, 1),
            "stages": [outcome.__dict__ for outcome in outcomes],
        }
        if not args.dry_run:
            _write_orchestrator_log(db_path, outcomes)
        return result

    total_elapsed = time.time() - start
    outcome_map = {o.stage: o for o in outcomes}
    _progress(f"DONE in {total_elapsed:.1f}s")
    summary = _format_summary(outcome_map)
    telegram_status = _send_telegram_summary(summary, no_telegram=args.no_telegram)
    if not args.dry_run:
        _write_orchestrator_log(db_path, outcomes)
    return {
        "ok": True,
        "elapsed_s": round(total_elapsed, 1),
        "telegram": telegram_status,
        "stages": [outcome.__dict__ for outcome in outcomes],
        "summary": summary,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meridian Stage 7 orchestrator")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--stage", default="all")
    parser.add_argument("--skip-cache", action="store_true")
    parser.add_argument("--full-refresh", action="store_true")
    parser.add_argument("--mock-ml", dest="mock_ml", action="store_true", default=True)
    parser.add_argument("--no-mock-ml", dest="mock_ml", action="store_false")
    parser.add_argument("--real-ml", action="store_true", help="Use real dual-TCN Stage 4 instead of mock")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--prop-firm", default="ftmo")
    parser.add_argument("--debug", default=None)
    parser.add_argument("--days", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_orchestrator(args)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
