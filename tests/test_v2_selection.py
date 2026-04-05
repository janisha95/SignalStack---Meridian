from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from stages import v2_selection as mod


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
        ("AAA", 100.0, 0.35),
        ("BBB", 100.0, -0.10),
        ("CCC", 50.0, 0.05),
    )
    for ticker, start_price, drift in specs:
        price = start_price
        for i in range(90):
            price += drift + ((i % 5) - 2) * 0.01
            d = (start + timedelta(days=i)).isoformat()
            rows.append((ticker, d, price - 0.2, price + 0.4, price - 0.5, price, 1_000_000.0, "alpaca"))
    con.executemany(
        "INSERT INTO daily_bars (ticker, date, open, high, low, close, volume, source) VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    pref_rows = [
        ("2026-03-25", "SPY", "TRENDING", 500.0, 1_000_000.0, 90, 0.02, 25.0, "ETF"),
        ("2026-03-25", "AAA", "TRENDING", 100.0, 1_000_000.0, 90, 0.02, 25.0, "Tech"),
        ("2026-03-25", "BBB", "TRENDING", 100.0, 1_000_000.0, 90, 0.02, 25.0, "Tech"),
        ("2026-03-25", "CCC", "CHOPPY", 50.0, 1_000_000.0, 90, 0.02, 20.0, "Energy"),
    ]
    con.executemany(
        "INSERT INTO prefilter_results (date, ticker, regime, price, dollar_volume, bars_available, atr_pct, adx, sector) VALUES (?,?,?,?,?,?,?,?,?)",
        pref_rows,
    )
    con.execute(
        "INSERT INTO cache_meta (key, value, updated_at) VALUES ('prefilter_run_at','2026-03-25T17:00:00-04:00','2026-03-25T17:00:00-04:00')"
    )
    con.commit()
    con.close()


def test_generate_mock_predictions_is_deterministic() -> None:
    df = pd.DataFrame({"ticker": ["SPY", "AAA", "BBB"], "price": [500.0, 100.0, 90.0]})
    a = mod.generate_mock_predictions(df)
    b = mod.generate_mock_predictions(df)
    pd.testing.assert_series_equal(a["predicted_return"], b["predicted_return"])


def test_compute_beta_known_relation() -> None:
    spy = pd.Series([0.01 + i * 0.001 for i in range(70)], dtype=float)
    ticker = spy * 2.0
    beta = mod.compute_beta(ticker, spy, window=60)
    assert beta == pytest.approx(2.0, rel=1e-6)


def test_selection_ranks_by_residual_not_raw_prediction(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)

    preds = pd.DataFrame(
        [
            {"ticker": "SPY", "predicted_return": 0.02, "regime": "TRENDING", "sector": "ETF", "price": 500.0},
            {"ticker": "AAA", "predicted_return": 0.03, "regime": "TRENDING", "sector": "Tech", "price": 100.0},
            {"ticker": "BBB", "predicted_return": 0.01, "regime": "TRENDING", "sector": "Tech", "price": 100.0},
        ]
    )
    monkeypatch.setattr(mod, "_load_predictions_frame", lambda db_path, mock: preds.copy())
    monkeypatch.setattr(
        mod,
        "_load_return_map",
        lambda db_path, tickers: {"SPY": pd.Series([0.01 + i * 0.0001 for i in range(70)], dtype=float)},
    )
    order = {"SPY": 1.0, "AAA": 2.0, "BBB": 0.1}
    call_tickers = iter(["SPY", "AAA", "BBB"])
    monkeypatch.setattr(
        mod,
        "compute_beta",
        lambda ticker_returns, spy_returns, window=60: order[next(call_tickers)],
    )
    shortlist = mod.select_shortlist(db_path=db_path, dry_run=True, mock=False, top_n=1, min_residual=0.0)
    assert shortlist.iloc[0]["ticker"] == "BBB"
    assert shortlist.iloc[0]["direction"] == "LONG"


def test_selection_writes_shortlist_daily(tmp_path: Path) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    frame = mod.select_shortlist(db_path=db_path, dry_run=False, mock=True, top_n=2, min_residual=0.0)
    con = sqlite3.connect(str(db_path))
    try:
        count = con.execute("SELECT COUNT(*) FROM shortlist_daily").fetchone()[0]
        cols = [r[1] for r in con.execute("PRAGMA table_info(shortlist_daily)").fetchall()]
    finally:
        con.close()
    assert count == len(frame)
    assert "top_shap_factors" in cols


def test_selection_replaces_prior_rows_for_same_date(tmp_path: Path) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE shortlist_daily (
                date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                predicted_return REAL,
                beta REAL,
                market_component REAL,
                residual_alpha REAL,
                rank INTEGER,
                regime TEXT,
                sector TEXT,
                price REAL,
                top_shap_factors TEXT,
                PRIMARY KEY (date, ticker)
            )
            """
        )
        con.execute(
            """
            INSERT INTO shortlist_daily (
                date, ticker, direction, predicted_return, beta, market_component,
                residual_alpha, rank, regime, sector, price, top_shap_factors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-03-26", "JUNK", "LONG", 0.9, 99.0, 0.0, 0.9, 999, "TRENDING", "Other", 10.0, None),
        )
        con.commit()
    finally:
        con.close()

    frame = mod.select_shortlist(db_path=db_path, dry_run=False, mock=True, top_n=2, min_residual=0.0)
    con = sqlite3.connect(str(db_path))
    try:
        junk = con.execute(
            "SELECT COUNT(*) FROM shortlist_daily WHERE date = ? AND ticker = ?",
            (mod.today_et(), "JUNK"),
        ).fetchone()[0]
        count = con.execute(
            "SELECT COUNT(*) FROM shortlist_daily WHERE date = ?",
            (mod.today_et(),),
        ).fetchone()[0]
    finally:
        con.close()
    assert junk == 0
    assert count == len(frame)


def test_selection_show_all_returns_ranked_universe_without_threshold(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)

    preds = pd.DataFrame(
        [
            {"ticker": "SPY", "predicted_return": 0.02, "regime": "TRENDING", "sector": "ETF", "price": 500.0, "shap_macro": 0.4},
            {"ticker": "AAA", "predicted_return": 0.03, "regime": "TRENDING", "sector": "Tech", "price": 100.0, "shap_quality": 0.8},
            {"ticker": "BBB", "predicted_return": -0.01, "regime": "TRENDING", "sector": "Tech", "price": 100.0, "shap_quality": -0.7},
            {"ticker": "CCC", "predicted_return": 0.005, "regime": "CHOPPY", "sector": "Energy", "price": 50.0, "shap_flow": 0.6},
        ]
    )
    monkeypatch.setattr(mod, "_load_predictions_frame", lambda db_path, mock: preds.copy())
    monkeypatch.setattr(
        mod,
        "_load_return_map",
        lambda db_path, tickers: {
            "SPY": pd.Series([0.01 + i * 0.0001 for i in range(70)], dtype=float),
            "AAA": pd.Series([0.012 + i * 0.0001 for i in range(70)], dtype=float),
            "BBB": pd.Series([0.008 + i * 0.0001 for i in range(70)], dtype=float),
            "CCC": pd.Series([0.009 + i * 0.0001 for i in range(70)], dtype=float),
        },
    )
    monkeypatch.setattr(mod, "compute_beta", lambda ticker_returns, spy_returns, window=60: 1.0)
    frame = mod.select_shortlist(db_path=db_path, dry_run=True, mock=False, show_all=True)
    assert set(frame["ticker"]) == {"AAA", "BBB", "CCC"}
    assert set(frame["direction"]) == {"LONG", "SHORT"}
    assert any(bool(v) for v in frame["top_shap_factors"].fillna(""))


def test_selection_clamps_extreme_betas(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)

    preds = pd.DataFrame(
        [
            {"ticker": "SPY", "predicted_return": 0.02, "regime": "TRENDING", "sector": "ETF", "price": 500.0},
            {"ticker": "AAA", "predicted_return": 0.03, "regime": "TRENDING", "sector": "Tech", "price": 100.0},
            {"ticker": "BBB", "predicted_return": -0.01, "regime": "TRENDING", "sector": "Tech", "price": 100.0},
        ]
    )
    monkeypatch.setattr(mod, "_load_predictions_frame", lambda db_path, mock: preds.copy())
    monkeypatch.setattr(
        mod,
        "_load_return_map",
        lambda db_path, tickers: {"SPY": pd.Series([0.01 + i * 0.0001 for i in range(70)], dtype=float)},
    )
    values = iter([10.0, -9.0, 1.0])
    monkeypatch.setattr(mod, "compute_beta", lambda ticker_returns, spy_returns, window=60: next(values))
    frame = mod.select_shortlist(db_path=db_path, dry_run=True, mock=False, show_all=True)
    assert frame["beta"].abs().max() <= mod.BETA_CLAMP
