from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from stages import v2_factor_engine as engine
from stages import v2_prefilter as prefilter


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
        CREATE TABLE cache_meta (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        CREATE TABLE options_daily (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            pcr REAL,
            unusual_vol_ratio REAL,
            net_delta REAL,
            source TEXT,
            PRIMARY KEY (ticker, date)
        );
        """
    )
    con.execute("INSERT INTO cache_meta (key, value, updated_at) VALUES ('stage1_validation_status','PASS','2026-03-25T00:00:00Z')")
    start = date(2025, 1, 1)
    rows = []
    for ticker, start_price, drift, volume in (
        ("SPY", 500.0, 0.2, 1_000_000.0),
        ("AAPL", 180.0, 0.15, 700_000.0),
        ("MSFT", 400.0, 0.12, 650_000.0),
        ("VIXY", 20.0, 0.01, 200_000.0),
    ):
        price = start_price
        for i in range(260):
            price += drift + ((i % 7) - 3) * 0.03
            d = (start + timedelta(days=i)).isoformat()
            rows.append((ticker, d, price - 0.2, price + 0.4, price - 0.5, price, volume + (i % 20) * 1000, "alpaca_bars_nightly"))
    con.executemany("INSERT INTO daily_bars (ticker, date, open, high, low, close, volume, source) VALUES (?,?,?,?,?,?,?,?)", rows)
    con.executemany(
        "INSERT INTO options_daily (ticker, date, pcr, unusual_vol_ratio, net_delta, source) VALUES (?,?,?,?,?,?)",
        [
            ("AAPL", "2026-03-25", 0.9, 1.1, 0.2, "yfinance_options"),
            ("MSFT", "2026-03-25", 1.1, 0.8, -0.1, "yfinance_options"),
        ],
    )
    con.commit()
    con.close()


def test_factor_engine_dry_run_and_write(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = tmp_path / "ticker_sector_map.json"
    sector_map.write_text(json.dumps({"AAPL": "Technology", "MSFT": "Technology", "SPY": "ETF", "VIXY": "ETF"}), encoding="utf-8")

    monkeypatch.setattr(engine, "SECTOR_MAP_PATH", sector_map)
    monkeypatch.setattr(prefilter, "SECTOR_MAP_PATH", sector_map)
    monkeypatch.setattr(prefilter, "DATA_DIR", tmp_path)
    monkeypatch.setattr(prefilter, "ROOT", tmp_path)

    dry = engine.run_engine(db_path=db_path, workers=2, dry_run=True)
    assert not dry.empty
    assert "ticker" in dry.columns

    written = engine.run_engine(db_path=db_path, workers=2, dry_run=False)
    assert not written.empty

    con = sqlite3.connect(str(db_path))
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "factor_matrix_daily" in tables
        count = con.execute("SELECT COUNT(*) FROM factor_matrix_daily").fetchone()[0]
        assert count == len(written)
    finally:
        con.close()


def test_factor_engine_debug_mode(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = tmp_path / "ticker_sector_map.json"
    sector_map.write_text(json.dumps({"AAPL": "Technology", "SPY": "ETF", "VIXY": "ETF"}), encoding="utf-8")
    monkeypatch.setattr(engine, "SECTOR_MAP_PATH", sector_map)
    monkeypatch.setattr(prefilter, "SECTOR_MAP_PATH", sector_map)
    monkeypatch.setattr(prefilter, "DATA_DIR", tmp_path)
    monkeypatch.setattr(prefilter, "ROOT", tmp_path)

    debug = engine.run_engine(db_path=db_path, workers=1, dry_run=True, debug_ticker="AAPL")
    assert len(debug) == 1
    assert debug.iloc[0]["ticker"] == "AAPL"


def test_factor_engine_uses_cached_prefilter_results(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = tmp_path / "ticker_sector_map.json"
    sector_map.write_text(json.dumps({"AAPL": "Technology", "MSFT": "Technology", "SPY": "ETF", "VIXY": "ETF"}), encoding="utf-8")

    monkeypatch.setattr(engine, "SECTOR_MAP_PATH", sector_map)
    monkeypatch.setattr(prefilter, "SECTOR_MAP_PATH", sector_map)
    monkeypatch.setattr(prefilter, "DATA_DIR", tmp_path)
    monkeypatch.setattr(prefilter, "ROOT", tmp_path)

    # First run seeds today's cached prefilter_results.
    first = engine.run_engine(db_path=db_path, workers=1, dry_run=False)
    assert not first.empty

    def _boom(*args, **kwargs):
        raise AssertionError("run_prefilter should not be called when cache is fresh")

    monkeypatch.setattr(engine, "run_prefilter", _boom)
    second = engine.run_engine(db_path=db_path, workers=1, dry_run=True, prefilter_cache=True)
    assert not second.empty
    assert set(second["ticker"]) == set(first["ticker"])


def test_factor_engine_skip_prefilter_requires_cache(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    sector_map = tmp_path / "ticker_sector_map.json"
    sector_map.write_text(json.dumps({"AAPL": "Technology", "SPY": "ETF", "VIXY": "ETF"}), encoding="utf-8")
    monkeypatch.setattr(engine, "SECTOR_MAP_PATH", sector_map)

    with pytest.raises(engine.FactorEngineError, match="skip-prefilter"):
        engine.run_engine(db_path=db_path, workers=1, dry_run=True, skip_prefilter=True)
