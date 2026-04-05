from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from stages import v2_training_backfill as mod


def _seed_db(db_path: Path) -> None:
    con = sqlite3.connect(str(db_path))
    con.executescript(
        """
        CREATE TABLE daily_bars (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            source TEXT,
            PRIMARY KEY (ticker, date)
        );
        """
    )
    start = date(2025, 1, 1)
    rows = []
    specs = (
        ("SPY", 500.0, 0.4, 1_500_000.0),
        ("AAPL", 180.0, 0.5, 900_000.0),
        ("MSFT", 400.0, 0.3, 850_000.0),
        ("VIXY", 20.0, 0.02, 200_000.0),
        ("PENNY", 0.8, 0.0, 900_000.0),
    )
    for ticker, start_price, drift, volume in specs:
        price = start_price
        for i in range(240):
            price += drift + ((i % 5) - 2) * 0.02
            d = (start + timedelta(days=i)).isoformat()
            rows.append(
                (
                    ticker,
                    d,
                    price - 0.2,
                    price + 0.4,
                    price - 0.5,
                    price,
                    volume + (i % 20) * 1000,
                    "alpaca_bars_nightly",
                )
            )
    con.executemany(
        """
        INSERT INTO daily_bars (ticker, date, open, high, low, close, volume, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()
    con.close()


def _sector_map(tmp_path: Path) -> Path:
    path = tmp_path / "ticker_sector_map.json"
    path.write_text(
        json.dumps(
            {
                "AAPL": "Technology",
                "MSFT": "Technology",
                "SPY": "ETF",
                "VIXY": "ETF",
                "PENNY": "Speculative",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_forward_return_computation_is_correct(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    all_ohlcv = mod._load_all_ohlcv(db_path)
    df = all_ohlcv["AAPL"]
    current_date = df["date"].iloc[200]
    got = mod.compute_forward_return(all_ohlcv, "AAPL", current_date, horizon=5)
    expected = (df["close"].iloc[205] / df["close"].iloc[200]) - 1.0
    assert got == pytest.approx(expected)


def test_forward_return_nan_when_insufficient_future_bars(tmp_path) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    all_ohlcv = mod._load_all_ohlcv(db_path)
    df = all_ohlcv["AAPL"]
    current_date = df["date"].iloc[-3]
    got = mod.compute_forward_return(all_ohlcv, "AAPL", current_date, horizon=5)
    assert pd.isna(got)


def test_slice_up_to_date_has_no_lookahead(tmp_path) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    all_ohlcv = mod._load_all_ohlcv(db_path)
    df = all_ohlcv["AAPL"]
    current_date = df["date"].iloc[120]
    sliced = mod._slice_up_to_date(df, current_date)
    assert sliced["date"].max() == current_date
    assert len(sliced) == 121


def test_historical_prefilter_removes_sub_dollar_ticker(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = _sector_map(tmp_path)
    monkeypatch.setattr(mod.factor_engine, "SECTOR_MAP_PATH", sector_map)
    all_ohlcv = mod._load_all_ohlcv(db_path)
    current_date = all_ohlcv["SPY"]["date"].iloc[150]
    survivors, _meta = mod._historical_prefilter(
        all_ohlcv,
        current_date,
        allowed_tickers=None,
        sector_map=mod.factor_engine._load_sector_map(),
    )
    assert "AAPL" in survivors
    assert "PENNY" not in survivors


def test_training_rows_have_active_factor_columns_and_target(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = _sector_map(tmp_path)
    monkeypatch.setattr(mod.factor_engine, "SECTOR_MAP_PATH", sector_map)
    monkeypatch.setattr(mod, "REPORT_PATH", tmp_path / "backfill_report.json")
    result = mod.run_backfill(
        db_path=db_path,
        start_date="2025-07-01",
        end_date="2025-07-03",
        tickers="AAPL,MSFT",
        workers=1,
        batch_days=1,
        dry_run=False,
    )
    frame = result["frame"]
    active = [entry["name"] for entry in mod.factor_engine._active_registry_entries(mod._load_registry())]
    for col in ["date", "ticker", *active, "forward_return_5d", "regime", "sector", "price"]:
        assert col in frame.columns


def test_insert_or_replace_is_idempotent(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = _sector_map(tmp_path)
    monkeypatch.setattr(mod.factor_engine, "SECTOR_MAP_PATH", sector_map)
    monkeypatch.setattr(mod, "REPORT_PATH", tmp_path / "backfill_report.json")
    kwargs = dict(
        db_path=db_path,
        start_date="2025-07-01",
        end_date="2025-07-03",
        tickers="AAPL,MSFT",
        workers=1,
        batch_days=1,
        dry_run=False,
    )
    first = mod.run_backfill(**kwargs)
    second = mod.run_backfill(**kwargs)
    con = sqlite3.connect(str(db_path))
    try:
        count = con.execute("SELECT COUNT(*) FROM training_data").fetchone()[0]
    finally:
        con.close()
    assert count == len(second["frame"]) == len(first["frame"])


def test_sample_limits_ticker_count(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = _sector_map(tmp_path)
    monkeypatch.setattr(mod.factor_engine, "SECTOR_MAP_PATH", sector_map)
    result = mod.run_backfill(
        db_path=db_path,
        start_date="2025-07-01",
        end_date="2025-07-03",
        sample=1,
        workers=1,
        dry_run=True,
    )
    tickers = set(result["frame"]["ticker"].tolist())
    assert len(tickers) <= 1


def test_dry_run_does_not_write_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = _sector_map(tmp_path)
    monkeypatch.setattr(mod.factor_engine, "SECTOR_MAP_PATH", sector_map)
    mod.run_backfill(
        db_path=db_path,
        start_date="2025-07-01",
        end_date="2025-07-03",
        tickers="AAPL,MSFT",
        workers=1,
        dry_run=True,
    )
    con = sqlite3.connect(str(db_path))
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    finally:
        con.close()
    assert "training_data" not in tables


def test_debug_prints_factor_dump(tmp_path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = _sector_map(tmp_path)
    monkeypatch.setattr(mod.factor_engine, "SECTOR_MAP_PATH", sector_map)
    mod.run_backfill(
        db_path=db_path,
        start_date="2025-07-01",
        end_date="2025-07-03",
        debug_ticker="AAPL",
        workers=1,
        dry_run=True,
    )
    captured = capsys.readouterr().out
    assert "[backfill] Debug mode: AAPL" in captured
    assert "forward_return_5d:" in captured
