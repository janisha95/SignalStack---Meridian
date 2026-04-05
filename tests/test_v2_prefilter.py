from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from stages import v2_prefilter as mod


def _use_tmp_meridian(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)


def _seed_db(db_path: Path, validation: str = "PASS") -> None:
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
        """
    )
    con.execute(
        "INSERT INTO cache_meta (key, value, updated_at) VALUES (?, ?, ?)",
        ("validation_status", validation, "2026-03-25T00:00:00Z"),
    )
    con.commit()
    con.close()


def _insert_ticker(
    db_path: Path,
    ticker: str,
    *,
    bars: int = 60,
    start_price: float = 10.0,
    price_step: float = 0.2,
    volume: float = 100_000.0,
) -> None:
    con = sqlite3.connect(str(db_path))
    start = date(2026, 1, 1)
    rows = []
    for i in range(bars):
        close = start_price + price_step * i
        d = (start + timedelta(days=i)).isoformat()
        rows.append(
            (
                ticker,
                d,
                close - 0.2,
                close + 0.3,
                close - 0.3,
                close,
                volume,
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


def _write_sector_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sector_map = tmp_path / "ticker_sector_map.json"
    sector_map.write_text(json.dumps({"SPY": "ETF", "GOOD": "Technology", "TREND": "Energy"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(mod, "SECTOR_MAP_PATH", sector_map)
    return sector_map


def test_tickers_below_floor_price_are_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "GOOD", start_price=10.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "PENNY", start_price=0.5, price_step=0.0, volume=1_000_000.0)

    df = mod.run_prefilter(db_path)
    assert "GOOD" in set(df["ticker"])
    assert "PENNY" not in set(df["ticker"])


def test_tickers_below_dollar_volume_floor_are_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "LIQ", start_price=20.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "THIN", start_price=20.0, price_step=0.1, volume=5_000.0)

    df = mod.run_prefilter(db_path)
    assert "LIQ" in set(df["ticker"])
    assert "THIN" not in set(df["ticker"])


def test_suffix_exclusions_remove_special_security_types(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "GOOD", start_price=10.0, price_step=0.1, volume=1_000_000.0)
    for ticker in ("BAD.WS", "BAD.WT", "BAD.U", "BAD.R"):
        _insert_ticker(db_path, ticker, start_price=10.0, price_step=0.1, volume=1_000_000.0)

    df = mod.run_prefilter(db_path)
    got = set(df["ticker"])
    assert "GOOD" in got
    assert "BAD.WS" not in got
    assert "BAD.WT" not in got
    assert "BAD.U" not in got
    assert "BAD.R" not in got


def test_tickers_with_less_than_min_bars_are_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "GOOD", bars=60, start_price=10.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "NEWB", bars=20, start_price=10.0, price_step=0.1, volume=1_000_000.0)

    df = mod.run_prefilter(db_path, min_bars=50)
    assert "GOOD" in set(df["ticker"])
    assert "NEWB" not in set(df["ticker"])


def test_spy_always_survives_all_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", bars=20, start_price=0.8, price_step=0.0, volume=100.0)

    df = mod.run_prefilter(db_path, min_bars=50, min_price=5.0, min_dollar_volume=1_000_000.0)
    assert set(df["ticker"]) == {"SPY"}


def test_every_survivor_has_valid_regime_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "TREND", start_price=10.0, price_step=0.8, volume=1_000_000.0)

    df = mod.run_prefilter(db_path)
    assert set(df["regime"]).issubset(mod.REGIMES)


def test_no_negative_prices_in_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "GOOD", start_price=10.0, price_step=0.1, volume=1_000_000.0)

    df = mod.run_prefilter(db_path)
    assert (df["price"] >= 0).all()


def test_aborts_if_db_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    with pytest.raises(mod.PrefilterError, match="missing"):
        mod.run_prefilter(db_path)


def test_aborts_if_validation_status_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path, validation="FAIL")
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)

    with pytest.raises(mod.PrefilterError, match="not PASS"):
        mod.run_prefilter(db_path)


def test_running_twice_produces_same_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "GOOD", start_price=10.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "TREND", start_price=10.0, price_step=0.8, volume=1_000_000.0)

    df1 = mod.run_prefilter(db_path)
    df2 = mod.run_prefilter(db_path)
    pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))


def test_dry_run_does_not_write_prefilter_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "GOOD", start_price=10.0, price_step=0.1, volume=1_000_000.0)

    mod.run_prefilter(db_path, dry_run=True)
    con = sqlite3.connect(str(db_path))
    try:
        keys = [r[0] for r in con.execute("SELECT key FROM cache_meta ORDER BY key").fetchall()]
    finally:
        con.close()
    assert keys == ["validation_status"]


def test_prefilter_persists_results_table_on_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "GOOD", start_price=10.0, price_step=0.1, volume=1_000_000.0)

def test_leveraged_inverse_etfs_are_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_tmp_meridian(tmp_path, monkeypatch)
    _write_sector_map(tmp_path, monkeypatch)
    db_path = tmp_path / "v2_universe.db"
    _seed_db(db_path)
    _insert_ticker(db_path, "SPY", start_price=500.0, price_step=0.1, volume=1_000_000.0)
    _insert_ticker(db_path, "GOOD", start_price=10.0, price_step=0.1, volume=1_000_000.0)
    for ticker in ("SOXS", "JDST", "TQQQ", "SDOW", "UVXY", "TSLL"):
        _insert_ticker(db_path, ticker, start_price=20.0, price_step=0.1, volume=5_000_000.0)

    df = mod.run_prefilter(db_path)
    got = set(df["ticker"])
    assert "GOOD" in got
    for ticker in ("SOXS", "JDST", "TQQQ", "SDOW", "UVXY", "TSLL"):
        assert ticker not in got

    df = mod.run_prefilter(db_path, dry_run=False)
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT date, ticker, regime FROM prefilter_results ORDER BY ticker ASC"
        ).fetchall()
    finally:
        con.close()
    assert len(rows) == len(df)
    assert [row[1] for row in rows] == sorted(df["ticker"].tolist())
