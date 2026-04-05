from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from stages import v2_risk_filters as mod


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
        CREATE TABLE prefilter_results (
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
        );
        """
    )
    start = date(2025, 1, 1)
    rows = []
    specs = (
        ("SPY", 500.0, 0.20),
        ("AAA", 100.0, 0.50),
        ("BBB", 90.0, 0.48),
        ("CCC", 50.0, -0.20),
        ("DDD", 40.0, 0.10),
    )
    for ticker, start_price, drift in specs:
        price = start_price
        for i in range(120):
            price += drift + ((i % 5) - 2) * 0.02
            d = (start + timedelta(days=i)).isoformat()
            rows.append((ticker, d, price - 0.2, price + 0.4, price - 0.5, price, 1_000_000.0, "alpaca"))
    con.executemany(
        "INSERT INTO daily_bars (ticker, date, open, high, low, close, volume, source) VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    pref_rows = [
        ("2026-03-25", "AAA", "TRENDING", 100.0, 1_000_000.0, 120, 0.02, 25.0, "Tech"),
        ("2026-03-25", "BBB", "TRENDING", 90.0, 1_000_000.0, 120, 0.02, 25.0, "Tech"),
        ("2026-03-25", "CCC", "TRENDING", 50.0, 1_000_000.0, 120, 0.02, 25.0, "Energy"),
        ("2026-03-25", "DDD", "TRENDING", 40.0, 1_000_000.0, 120, 0.02, 25.0, "Tech"),
        ("2026-03-25", "SPY", "TRENDING", 500.0, 5_000_000.0, 120, 0.01, 20.0, "ETF"),
    ]
    con.executemany(
        "INSERT INTO prefilter_results (date, ticker, regime, price, dollar_volume, bars_available, atr_pct, adx, sector) VALUES (?,?,?,?,?,?,?,?,?)",
        pref_rows,
    )
    con.commit()
    con.close()


def test_load_risk_config_preset_override() -> None:
    cfg = mod.load_risk_config(prop_firm="myfundedtrader", account_balance=120000)
    assert cfg["account_balance"] == 120000
    assert cfg["max_total_drawdown_pct"] == 0.08


def test_compute_position_math() -> None:
    cfg = mod.load_risk_config(prop_firm="ftmo")
    state = {
        "daily_loss_remaining": 5000.0,
    }
    pos = mod.compute_position("AAA", "LONG", 100.0, 2.5, cfg, state)
    assert pos is not None
    assert pos["shares"] == 100
    assert pos["stop_price"] == 95.0
    assert pos["tp_price"] == 110.0


def test_check_correlation_blocks_highly_correlated_series() -> None:
    a = pd.DataFrame({"close": [100 + i for i in range(80)]})
    b = pd.DataFrame({"close": [50 + i * 2 for i in range(80)]})
    ok, ticker, corr = mod.check_correlation("AAA", ["BBB"], {"AAA": a, "BBB": b}, 0.85)
    assert not ok
    assert ticker == "BBB"
    assert corr is not None and corr > 0.85


def test_risk_filters_sector_cap(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    con = sqlite3.connect(str(db_path))
    try:
        con.executescript(
            """
            CREATE TABLE trade_log (
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
        con.executemany(
            "INSERT INTO trade_log (ticker, direction, entry_date, entry_price, shares, risk_dollars) VALUES (?,?,?,?,?,?)",
            [
                ("T1", "LONG", "2026-03-24", 100.0, 10, 500.0),
                ("T2", "LONG", "2026-03-24", 100.0, 10, 500.0),
                ("T3", "LONG", "2026-03-24", 100.0, 10, 500.0),
            ],
        )
        con.executemany(
            "INSERT INTO prefilter_results (date, ticker, regime, price, dollar_volume, bars_available, atr_pct, adx, sector) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("2026-03-25", "T1", "TRENDING", 100.0, 1_000_000.0, 120, 0.02, 25.0, "Tech"),
                ("2026-03-25", "T2", "TRENDING", 100.0, 1_000_000.0, 120, 0.02, 25.0, "Tech"),
                ("2026-03-25", "T3", "TRENDING", 100.0, 1_000_000.0, 120, 0.02, 25.0, "Tech"),
            ],
        )
        con.commit()
    finally:
        con.close()
    shortlist = pd.DataFrame(
        [
            {"ticker": "AAA", "direction": "LONG", "predicted_return": 0.03, "beta": 1.0, "residual_alpha": 0.03, "rank": 1, "regime": "TRENDING", "sector": "Tech", "price": 100.0},
            {"ticker": "CCC", "direction": "LONG", "predicted_return": 0.028, "beta": 1.0, "residual_alpha": 0.028, "rank": 3, "regime": "TRENDING", "sector": "Energy", "price": 80.0},
        ]
    )
    monkeypatch.setattr(mod, "_load_shortlist", lambda db_path, mock, show_all=False: shortlist.copy())
    monkeypatch.setattr(mod, "check_correlation", lambda ticker, existing_positions, ohlcv_dict, threshold=0.85: (True, None, None))
    portfolio, state = mod.build_tradeable_portfolio(db_path=db_path, dry_run=True, mock=False)
    verdicts = {row["ticker"]: (row["filter_status"], row["filter_reason"]) for _, row in portfolio.iterrows()}
    assert verdicts["AAA"] == ("REJECTED", "SECTOR_CAP")
    assert verdicts["CCC"][0] == "APPROVED"


def test_risk_filters_writes_tables(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    shortlist = pd.DataFrame(
        [
            {"ticker": "AAA", "direction": "LONG", "predicted_return": 0.03, "beta": 1.0, "residual_alpha": 0.03, "rank": 1, "regime": "TRENDING", "sector": "Tech", "price": 100.0},
            {"ticker": "CCC", "direction": "SHORT", "predicted_return": -0.03, "beta": 1.0, "residual_alpha": -0.03, "rank": 1, "regime": "TRENDING", "sector": "Energy", "price": 50.0},
        ]
    )
    monkeypatch.setattr(mod, "_load_shortlist", lambda db_path, mock, show_all=False: shortlist.copy())
    portfolio, state = mod.build_tradeable_portfolio(db_path=db_path, dry_run=False, mock=False)
    con = sqlite3.connect(str(db_path))
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "tradeable_portfolio" in tables
        assert "portfolio_state" in tables
        assert "trade_log" in tables
        count = con.execute("SELECT COUNT(*) FROM tradeable_portfolio").fetchone()[0]
        cols = [r[1] for r in con.execute("PRAGMA table_info(tradeable_portfolio)").fetchall()]
        assert count == len(portfolio)
    finally:
        con.close()
    assert "filter_reason" in cols


def test_manual_ticker_mode_uses_requested_direction(tmp_path: Path) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    portfolio, state = mod.build_tradeable_portfolio(
        db_path=db_path,
        dry_run=True,
        mock=False,
        tickers=["AAA"],
        directions=["SHORT"],
    )
    assert len(portfolio) == 1
    assert portfolio.iloc[0]["ticker"] == "AAA"
    assert portfolio.iloc[0]["direction"] == "SHORT"
